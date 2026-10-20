/* Linker script for a Cortex-M4 with 256 KiB of flash at 0x08000000 and 64 KiB of RAM at 0x20000000.
   Change the two lengths and origins for your chip. */
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x08000000, LENGTH = 256K
  RAM   (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

ENTRY(reset)
_estack = ORIGIN(RAM) + LENGTH(RAM);

/* Interrupt handlers the program does not define fall back to DefaultHandler. */
PROVIDE(NMI = DefaultHandler);
PROVIDE(HardFault = DefaultHandler);
PROVIDE(MemManage = DefaultHandler);
PROVIDE(BusFault = DefaultHandler);
PROVIDE(UsageFault = DefaultHandler);
PROVIDE(SVCall = DefaultHandler);
PROVIDE(DebugMon = DefaultHandler);
PROVIDE(PendSV = DefaultHandler);
PROVIDE(SysTick = DefaultHandler);

SECTIONS
{
  .vectors : {
    LONG(_estack);
    LONG(reset);
    LONG(NMI);
    LONG(HardFault);
    LONG(MemManage);
    LONG(BusFault);
    LONG(UsageFault);
    LONG(0); LONG(0); LONG(0); LONG(0);
    LONG(SVCall);
    LONG(DebugMon);
    LONG(0);
    LONG(PendSV);
    LONG(SysTick);
    KEEP(*(.isr_vector))      /* device interrupts: a table of `fn()` in a `@section(".isr_vector")` static */
  } > FLASH

  .text : {
    *(.text*)
    *(.rodata*)
    . = ALIGN(4);
  } > FLASH

  _sidata = LOADADDR(.data);
  .data : {
    _sdata = .;
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } > RAM AT > FLASH

  .bss (NOLOAD) : {
    _sbss = .;
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } > RAM

  /DISCARD/ : { *(.ARM.exidx*) *(.comment) }
}
