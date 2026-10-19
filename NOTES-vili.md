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

## XNU build state (2026-10-19)

- Repo now at `github.com/captajn/ios-vili` (push to upstream
  dipa-studio/ios-sweet denied for captajn). `origin`=captajn/ios-vili,
  `upstream`=dipa-studio/ios-sweet. Workflow `.github/workflows/xnu.yml`
  (macos-14 + Xcode, xnu-8796 via blacktop/darwin-xnu-build + patches).
- Push-triggered CI run **39237412087** = first vili xnu build
  (kernel_config DEVELOPMENT, machine SWEET, keep_going). Artifacts:
  `xnu-kernel` (kernel.development.sweet) + `xnu-buildtree`.
- Kernel patches adapted for lahaina (commit 8979b9d):
  - 0010/0012 early-FB debug: 0x9c000000 -> **0xea600000** (vili splash).
    The bootstrap TTE trick (+2*PGBYTES, "L1 index 0") still applies —
    with 16K granule one L1 entry covers 32 GB, so FB and both RAM
    banks are all L1 index 0. Verified reasoning, not yet boot-tested.
  - 0004 machine config: default VTIMER_INTID 19 -> **27**; REMOVED the
    `gicr_write32(GICR_IPRIORITYR0...)` loop — proven to external-abort
    on vili (FAR 0x17a70400). 0017 context updated to match.
  - 0017 already reads `virtual-timer-intid` from ADT (mkadt emits 27).
- Pending kernel-side work NOT yet done: touch (FTS/SPI 0xa8c000),
  keys (PMK8350 PON + PM8350 GPIO6), SPMI/PMIC paths, USB dwc3@a600000.
  Touch patches 0060-0063 are sweet-Goodix/I2C — must be rewritten.
- ADTs generated: `build/vili-highmem.adt` (dram 0x200000000+6G) and
  `build/vili-lowmem.adt` (0xf0000000 window). /product node missing —
  needs `research/ipsw-x/d22ap.adt` (extract from IPSW, gitignored).
- iPhone X 16.7.16 (20H392) IPSW downloaded:
  `research/ipsw-x/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw` (6.2 GB).
  `research/ipsw-x/d22ap.adt` extracted (real iPhone X device tree ->
  /product node now present in generated ADTs). DMGs extracted to
  `research/ipsw-x/dmgs/`: OS=`087-86698-044.dmg` (4.7G),
  SystemOS=`087-86593-047.dmg` (2.7G), AppOS=`087-86715-047.dmg` (10M).
- WSL tools for mkiosroot.sh installed: apfs-fuse (built from sgan81
  HEAD at /root/apfs-fuse, copied to /usr/local/bin; needed
  `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` + `#include <cstdint>` in
  ApfsLib/PList.h for GCC 15), hfsprogs (mkfs/fsck.hfsplus), fuse3,
  lzfse, rsync.

## First XNU boot attempt (2026-10-19, build run 39237412087)

kernel.development.sweet (17 MB Mach-O) + vili-highmem.adt payload +
appended via mkbootimg3 res2/res3. `fastboot boot` -> real XNU panic
screen (framebuffer panic UI works!):

    panic: Kernel data abort. at pc 0xfffffe0007a78ef4
    lr 0xfffffe0007a78ee0  esr 0x96000010 (external abort, write)
    far 0xfffffe000cd04080  (io_map VA -> PA 0x17a70080)

Symbolicated via LINKEDIT symtab (70,853 syms): pc/lr both inside
`_pe_init_fiq` (+0x1a0/+0x18c). Disasm: the faulting insn is
`str w9,[x8,#128]!` with w9=0xFFFFFFFF = `gicr_write32(GICR_IGROUPR0,
0xFFFFFFFF)` — the FIRST redist config write. So on lahaina, NS writes
to GICR_IGROUPR0 are XPU-blocked exactly like IPRIORITYR (the shim's
probe "passed" only because its posted device store dropped the write
silently — readback was never checked).

Fix (commit pending = "vili: drop GICR IGROUPR0 write"): remove the
IGROUPR0 write; keep ISENABLER0 (verified takes). Group assignment is
whatever QHEE left — Linux works, so SGI/PPI must already be in a
non-secure-visible group. SECOND build queued: CI run 39241159323.

Risk to watch: if PPIs/SGIs are actually Group0, the vtimer won't
deliver -> early hang later (calibration). If so, need to test whether
an IGROUPR0 write via different attributes/EL path works.

## Second XNU boot attempt (build 39241159323, IGROUPR0 write removed)

Progressed PAST pe_init_fiq — the IGROUPR0 fix worked. New panic:

    panic: Undefined kernel instruction
    pc=0xfffffe0007491340 instr/sleh.c:518  esr EC 0

Symbolicated: `_fiq_context_init`+0xc -> `_enable_virtual_timer()` in
osfmk/arm64/machine_routines.c. The faulting window contains
`msr cntv_ctl_el0` (ok on vili — shim proved it) immediately followed
by `msr cntp_ctl_el0` (proven to trap to QHEE -> injected undefined).
Patch 0082 drops the CNTP_CTL_EL0 write under SWEET. Build run
39243974933.

If the next panic still lands at the CNTV write itself, then QHEE
traps CNTV_CTL_EL0 in this specific context and the enable write must
be removed too (timer interrupt then enabled via CNTV_TVAL anyway).

## Third XNU boot (build 39243974933, CNTP_CTL skipped) — deep progress

Kernel now boots well past fiq_context_init. Framebuffer log shows
real XNU startup: platform expert registered, SWEET NDT/SURF/HID/
BATTERY/FB registrations (AppleCLCD bound to 0xea60000 1080x2400),
pmap/vm zone tables, "VM bootstrap done: 85 maps, 165 entries and
503 holes left", OSLog/firehose log queues, "standard timeslicing
quantum is 10000 us", "mig_table_max_displ = 54 mach_kobj_count = 374",
two "debug_log_init: Error!! gPanicBase is still not initialized"
(normal — no iBoot panic region), last line "kdp_core zlib memory
0x8000" (osfmk/kdp/output_stages/out_zlib.c:260, inside kdp_init).

STALL: boot hangs silently right after kdp_init. In kernel_bootstrap
(startup.c) the next steps are hv_support_init (HYPERVISOR),
bootprofile_init (CONFIG_TELEMETRY),
kernel_startup_initialize_upto(STARTUP_SUB_SYSCTL), PE_init_iokit,
kernel_startup_initialize_upto(STARTUP_SUB_EARLY_BOOT), spllo,
initialize_screen. No panic, no further output after >4 min.

startup_debug=1 boot-arg produced NO extra output (tunable parsed but
verbose prints absent — reason unclear; possibly not reaching the
kprintf gate or arg not applied). Patch 0083 instead adds
unconditional SWEET kprintf markers around each startup entry
(SE%02d.rank@func(arg) + SEok) and checkpoints SEB:hv/bp/sysctl/iokit/
eb/irqon so the next boot photo directly names the hanging entry.
Build run 39248634013.

## Fourth XNU boot (build 39248634013) — self-inflicted early panic

Panicked much earlier: "SWEET EARLY 4: cpu_bootstrap done" then
"invalid ticket lock 0xfffffe0007b904c8 <0x0 0x0 0x0 0x0>
@lock_ticket.c:134". Symbolicated: the lock is `_log_lock`
(osfmk/kern/printf.c:784, LCK_TICKET_DECLARE). It is initialized by a
startup hook STARTUP_ARG(LOCKS, RANK_FOURTH, lck_ticket_startup_init).
My 0083 kprintf inside the startup loop ran for entries BEFORE that
hook -> printf -> bsd_log_lock -> lck_ticket_lock on uninitialized
lock -> panic. The instrumentation itself caused the crash, NOT a
regression vs build 3.

Fix: 0083 now only prints when upto >= STARTUP_SUB_SYSCTL (the exact
region under investigation; log_lock/console all initialized by then).
Build run 39250323317.

Lesson: kprintf is NOT safe during early startup entries (LOCKS,
KPRINTF phases). Any future early instrumentation must write the
framebuffer directly like the SWEET EARLY markers, or stay >= SYSCTL.

## Fifth XNU boot (build 39252040725 + debug=0x10000c) — hypothesis FALSIFIED

Photo 2026-10-19 19:40 booted the repacked `debug=0x10000c` image (payload +
shim-boot.img built 19:37, kernel sha256 8a33c781... = run 39252040725).
Same stall as build 3, so DB_REBOOT_ALWAYS did nothing. Two root causes of
our blindness, both proven from source (local mirror `build/xnu-src/`,
fetched from apple-oss-distributions/xnu @ xnu-8796.101.5):

1. **The early-FB console WRAPS, it does not scroll.** Patch 0010 does
   `early_row = (early_row + 1) % EARLY_ROWS`, so the TOP line of a full
   screen is the NEWEST output. The photo's top line is
   `Serial requested, consistent debug disabled or debug boot arg not
   present, configuring debugging over serial` — that printf is
   kdp_udp.c ~:2288, i.e. AFTER `kdp_core_init()`. The ring boundary is
   confirmed by the last two prints being adjacent on-screen (bottom row
   `kdp_core zlib memory` -> top row `Serial requested`) and adjacent in
   program order. So the real last message is "Serial requested...", and
   the "hangs right after kdp_init" reading was accidentally right but for
   the wrong reason.
2. **Every 0083/0084 marker was swallowed.** They all call `kprintf`, and
   `pexpert/arm/pe_kprintf.c:105` requires `!disable_serial_output &&
   !disable_kprintf_output`. `disable_kprintf_output` is only cleared by the
   `-enable_kprintf_spam` boot-arg in DEVELOPMENT builds (pe_kprintf.c:47-52).
   `DB_KPRT = 0x8` (osfmk/kern/debug.h:516) was ALREADY set by `debug=0xc`,
   so the spam flag was the single missing piece. This also explains why
   `startup_debug=1` produced no output in build 3.

Also: `zlib_stage_initialize()` (out_zlib.c:246-260) has NO debug-flag gate —
the `kdp_core zlib memory 0x%lx` printf is simply the line before
`kmem_alloc(kernel_map, ...)`. `debug=0x10000c` could never skip it. Reverted
to `debug=0xc`: DB_REBOOT_ALWAYS would auto-reboot on panic and destroy the
framebuffer panic screen we read every iteration.

## Repack 19:53 (no rebuild): kprintf markers enabled

`python3 tools/mkpayload.py xnu/out/kernel.development.sweet
build/vili-highmem.adt build/payload.bin --cmdline "debug=0xc serial=3
cpus=1 keepsyms=1 -enable_kprintf_spam"` then `mkbootimg3.py --kernel
shim/out/Image --payload build/payload.bin` (shim Image unchanged from 18:29).
Image `shim/out/shim-boot.img` 16,867,424 B, sha256 `592ea5328dd11b68...`,
same kernel 8a33c781... Expected: the compiled-in SEK:pkt/SEK:core,
KOS:buf/net/pro/shm/mba/done and SEB:hv/bp/sysctl/iokit/eb/irqon markers now
appear, naming the exact hang. Caveat: kprintf goes through `PE_kputc`, which
is `serial_putc_crlf` if `serial_init()` succeeded — our ADT has no
uart0/PI3/gpio node (scanned), so it must fall back to
`console_write_unbuffered` (framebuffer). If the next photo shows NO markers
at all, the serial path is live and the fix is to rebuild 0083/0084 with
`printf` instead of `kprintf`.

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

1. Wait for CI run 39237412087 -> download `xnu-kernel` artifact ->
   `tools/mkpayload.py kernel build/vili-highmem.adt build/payload.bin`
   -> append via `tools/mkbootimg3.py --payload` -> `fastboot boot`.
   First xnu attempt: cpus=1, watch for early-FB marks / panic text.
2. Then iOS root image (mkiosroot.sh needs apfs-fuse + hfsplus tools in
   WSL + the IPSW dmgs) -> userdata per AGENTS.md approval (confirm
   before any flash — still fastboot-boot-only until then).
3. Touch driver for FTS-over-GENI-SPI; keys via PMK8350 PON.

Artifacts kept out of git: E:\Code\Rom\vili\ (backups, live FDT, ROM).
Build deps on Windows/WSL: aarch64-linux-gnu-gcc, python3. mkbootimg is
no longer needed (mkbootimg3.py replaces it for v3).
