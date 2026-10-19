#pragma once
#include <stdint.h>

/* Boot the SWEETXNU payload from the ABL ramdisk (boot v2 initrd) or from the
 * blob appended behind the shim image (boot v3 res2/res3); returns only on error. */
const char *loader_boot(uintptr_t dtb);
