# ios-vili: XNU/iOS on Xiaomi 11T Pro (vili, SM8350/lahaina)

Port of ios-sweet (NOTES.md is the original sweet handoff) to the Xiaomi
11T Pro. This file is the active handoff for the vili port — update it
after each milestone per AGENTS.md.

## Goal

Same architecture as sweet: stock ABL -> `fastboot boot` shim -> xnu +
generated ADT -> iOS 16.7.16 (iPhone X / D22AP) userland on the internal
UFS. Keep Android recoverable; confirm every destructive step first.

## Hardware facts (from the live FDT, not guesses)

Dumped from the phone via OrangeFox (see E:\Code\Rom\vili\live-dt\vili-live.fdt,
backup of 16 partitions in E:\Code\Rom\vili\backup). ABL merges dtb_idx=0
(Lahaina V2.1) + dtbo_idx=29 ("Odin" tree — Xiaomi shares it for vili).

- RAM 12 GiB, three banks: `0x80000000+0x37500000`, `0xc0000000+0x140000000`,
  `0x200000000+0x180000000`. Top bank (6 GiB) has zero reserved carve-outs.
- Mid-bank carve-outs: removed_region@d8800000+0xa000000,
  splash@ea600000+0x2300000, dfps@ec900000+0x100000. Clean window
  0xeca00000-0x200000000 (~4.3 GiB).
- Framebuffer: splash_region `0xea600000` +0x2300000, 1080x2400 ARGB
  (panel dsi_k3s_42_02_0a_dsc_cmd, DSC command mode).
- GICv3: 0x17a00000 / redist 0x17a60000 — same addresses as sm7150.
  Timers standard ARM: VTIMER PPI 11 (INTID 27), PTIMER PPI 14 (INTID 30).
- UFS host 0x1d84000 (androidboot.bootdevice=1d84000.ufshc), same base as
  sweet; PHY at 0x1d87000. UFS 3.1 — clocks/PHY init not yet validated.
- USB: dwc3@a600000.
- Touch: ST FingerTipS on GENI SPI, /soc/spi@a8c000/fts@0 (qupv3_1 SE11),
  7 MHz, IRQ GPIO23 (<0x17 0x2008>), reset GPIO22. NOT Goodix/I2C like
  sweet — needs a new driver.
- PMIC: PMK8350 pon_hlos@1300, SPMI arbiter 0xc440000. No MMIO pshold on
  lahaina (sweet's 0x0c264000 does not exist); reset via PSCI_SYSTEM_RESET.
- imem: qcom,msm-imem@146bf000, restart_reason +0x65c -> 0x146bf65c.
- CPUs: 8 cores, MPIDR Aff1 = index. 0-3 A55 (cap 1024, fd0), 4-6 A78
  (cap 1946, fd1), 7 X1 prime (cap 2048, fd2).
- Boot: ANDROID! header_version 3. Stock kernel_addr=0x12f67c0,
  os_version=0x1a000198. boot.img has no ramdisk; vendor_boot.img holds
  vendor ramdisks; dtb.img has 10 concatenated FDTs (idx 0 = Lahaina V2.1).

## What changed vs sweet (this repo)

- `shim/console.h`, `shim/mmu.h`: FB_PHYS/FB_BASE = 0xea600000.
- `shim/mmu.c`: L2 Device map extended to 16 GB (RAM ends 0x380000000).
- `shim/shim.c`: IMEM_RESTART_REASON 0x146bf65c; PSHOLD removed (PSCI
  reset only); VTIMER_INTID 27, PTIMER_INTID 30; labels say "vili".
  GIC bases and NR_CPUS=8 unchanged (same on lahaina).
- `shim/loader.c`: if /chosen has no linux,initrd-* (boot v3 has no
  ramdisk), the payload is read from the blob appended behind the shim
  image; mkbootimg3.py stores its file offset/size in the ARM64 header
  res2/res3 fields. initrd path kept for v2 compat.
- `tools/mkbootimg3.py`: new — minimal boot v3 packer + payload append.
- `shim/build_vili.sh`: builds shim -> Image -> mkbootimg3 (boot v3,
  kernel_addr/os_version copied from stock). No mkbootimg/dtb needed.
- `tools/mkadt.py`: vili constants (RAM windows, FB, VTIMER 27, kryo680 /
  SM8350 clocks, VILI_ECID, compatible += xiaomi,vili/qcom,sm8350).
  Kernel-facing names (sweet-io, sweet,display, sweet-ufs, xiaomi,sweet)
  intentionally kept so existing kernel patches still match.
- mkpayload.py, fdt.c, ufs.c, console.c: unchanged (generic or same base).

## Validated on hardware (2026-10-19, shim-boot.img via fastboot boot)

First probe boot, photographed framebuffer console:

- **Framebuffer 0xea600000 works** — console renders 1080x2400.
- **UFS read path works** — VER=0x300, CAP=0x1587031F, HCE=1, HCS=0x10f;
  took over ABL's UTRL (was 0x9ea5b000), SCSI TUR/CAP/READ(10) all rc=0.
  LUN0 lastlba=0x3afabff (4 KiB blocks, ~238 GiB). GPT parses:
  persist, super, cust(ext4), userdata @lba 0x2eec00 (0x380bf MiB).
- **DTB passed in x0** (magic D00DFEED at 0xae944000).
- **ABL sets /chosen linux,initrd-* even on boot v3** (region at
  ~0xaeb45000 containing non-payload data) -> loader must check the
  SWEETXNU magic, not just prop presence. Done: falls back to the
  res2/res3 appended payload.
- **MMU on with 16K granule works** (PARange=2 i.e. 40-bit PA, TG16=1).
  Identity map extended to 16 GiB covers RAM to 0x380000000.
- **PSCI 1.1 works**: PSCI_VERSION and SYSTEM_RESET both fine (phone
  reset back to Android by itself).
- **GICv3**: distributor already enabled (CTLR 0x53), redistributor found
  at 0x17a60000, IGROUPR0/ISENABLER0 writes take (bits 1,27,30 set).
  BUT: **writes to redist IPRIORITYR take an external abort**
  (FAR=0x17a70400, ESR=0x96000010) regardless of access size — reads are
  fine. We now leave priorities at default 0 (PMR 0xf0).
- **cntv_* timer regs work** — VTIMER INTID 27 fired 31 irqs in 300 ms;
  SGI self-send works (10 irqs). **cntp_ctl_el0 write traps to EL2**
  (EC 0x00, QHEE virtualizes the phys timer) — only clear it when armed.
- **SMP works**: PSCI_CPU_ON starts all 7 secondaries at our entry
  (mpidr 0x81000100..0x81000700, i.e. Aff1 index + bit31/MT). First
  500 ms poll showed only cores 5-7: cores 1-4 just start slower
  through the QHEE path — 2 s wait (+ MPIDR|bit31 retry) sees all 8.
  For xnu, keep a generous settle delay before counting CPUs.

## Open questions / guesses

- Whether dynamic memory pools (not in the DT) steal from the chosen RAM
  window — shim probe must verify. HIGH bank believed clean.
- Whether ABL passes a merged FDT in x0 on `fastboot boot` for v3 images
  (it did for normal boots on this device — the live FDT exists).
- UFS PHY/link state left by ABL on vili; ufs.c probe is read-only and
  will report VER/CAP/HCS first.
- No kernel addr requirement verified: we reuse stock kernel_addr.
- SPMI-based PSHOLD/reset (PMIC write via 0xc440000) not implemented;
  PSCI_SYSTEM_RESET is expected to work (TZ handles it).
- Touch (FTS over GENI SPI @0xa8c000) and buttons (PMK8350 PON, GPIO6)
  are unimplemented — probe-only stage.

## Next

1. WSL2: user approved install, restart pending — then install
   aarch64-linux-gnu-gcc in the distro and run shim/build_vili.sh.
2. `fastboot boot out/shim-boot.img` (no payload) -> expect the vili
   probe screens (UFS dump, GIC/timer, PAR of 0x300000000). Phone returns
   to Android by itself after ~3 min or via the power path.
3. Then mkadt --highmem payload + kernel build (GitHub Actions, same as
   sweet) and the first xnu attempt.

Artifacts kept out of git: E:\Code\Rom\vili\ (backups, live FDT, ROM).
Build deps on Windows/WSL: aarch64-linux-gnu-gcc, python3. mkbootimg is
no longer needed (mkbootimg3.py replaces it for v3).
