# hardboiled traps and warnings

What each error detected by the board means, why it usually happens and how to
find it with the debugger. Each section can be read from the terminal with
`hardboiled explain <kind>`.

<a id="null-pointer"></a>
## Null pointer (`null-pointer`)

Something was read or written at an address between `0x0` and `0xFFFF`: almost
always a pointer that is `NULL` (or `NULL` plus an offset, as in `p->field`).

Typical causes:

- a pointer that was declared and never initialized (on the stack it may be 0);
- a function that returns `NULL` to signal an error, and nobody checked it;
- walking a linked list past its last node.

How to find it: in the trap screen, the call stack shows who used the pointer.
In the **Variables** tab, look for the pointer that is `NULL`; `F8` goes back one
step, and a **watchpoint** (`w`) on the pointer shows where it got that value.

<a id="flash-write"></a>
## Write to Flash (`flash-write`)

Flash (`0x0001_0000`–`0x0001_FFFF`) holds the code and the constants and is
read-only. Trying to write to it is usually:

- modifying a string literal: `char *s = "hello"; s[0] = 'H';` — the literal
  lives in Flash; use `char s[] = "hello";` to get a copy in SRAM;
- writing through a pointer to `const` cast to non-`const`;
- a pointer that points to code by mistake.

<a id="unmapped"></a>
## Unmapped memory (`unmapped`)

The address belongs neither to Flash, SRAM nor the peripheral space. It is
usually an uninitialized pointer (holding garbage), an array index far out of
range, or wrong pointer arithmetic (adding bytes to an `int *`).

<a id="bad-jump"></a>
## Jump to an area without code (`bad-jump`)

The program jumped to an address that is not code: SRAM is not executable and
there are no instructions outside Flash. It is almost always:

- an uninitialized or corrupted **function pointer**;
- an **overwritten return address**: a local array written past its bounds
  (buffer overflow) overwrites the `ra` saved on the stack, and `return` jumps
  anywhere. The **Stack** tab shows where each saved `ra` is, and stepping back
  (`F8`) lets you see who wrote it.

<a id="stack-overflow"></a>
## Stack overflow (`stack-overflow`)

The stack grew until it ran into the global variables (or left SRAM). Every
call takes room on the stack: parameters, local variables, `ra` and `s0`.

- **Recursion without a base case** (or with one that is never reached): the
  call stack shows the same function repeated hundreds of times.
- **Huge local arrays**: `int buffer[20000];` inside a function does not fit in
  64 KB of SRAM; make it `static` or global.

<a id="misaligned"></a>
## Misaligned access (`misaligned`)

An `lw`/`sw` (4 bytes) needs an address that is a multiple of 4, and an
`lh`/`sh` one that is a multiple of 2. It usually happens when casting a
`char *` to an `int *` and reading "halfway through" a buffer, or with packed
structs. Copy the bytes with a loop (or `memcpy`) instead of casting the
pointer.

<a id="mmio"></a>
## Invalid MMIO access (`mmio`)

The peripheral space (`0x4000_0000`) was accessed at an offset with no
register, a read-only register (such as `SWITCHES`) was written, or the access
was misaligned. Use the macros and functions in `hardboiled.h` instead of
hand-written addresses; for a custom board, generate the SDK with
`hardboiled gen-header`.

<a id="wfi-deadlock"></a>
## wfi with nothing to wake the CPU (`wfi-deadlock`)

`wait_for_interrupt()` puts the CPU to sleep until an interrupt arrives, but
none can arrive: `attach_irq()` is missing for that line, `interrupts_enable()`
is missing, or the peripheral does not have its interrupt enabled (for example
`timer_start(period, 1)` with the 1, or `uart_rx_irq(1)`).

<a id="vector"></a>
## Invalid interrupt vector (`vector`)

An interrupt arrived but the vector table is missing or points outside the
code. It happens when the program was not linked with the runtime's `crt0.s`
and `hardboiled.ld`: compile with `hardboiled build` or `hardboiled run
file.c`.

<a id="isr-stack"></a>
## Unbalanced stack when returning from an interrupt (`isr-stack`)

When `mret` ran, `sp` was not where it was when the interrupt started, or
`mret` ran outside an interrupt. It is usually hand-written assembly that
changes `sp` without restoring it. ISRs written in C and registered with
`attach_irq()` do not have this problem.

<a id="exception"></a>
## CPU exception (`exception`)

The CPU found an instruction it cannot execute: usually because the program
jumped into data that is not code, or it was compiled for another
architecture. Check the failing instruction in the trap screen and compile with
`--march rv32i` (or `rv32im`/`rv32imc`).

<a id="limit"></a>
## Instruction limit (`limit`)

It is not an error: the program executed `max_instructions` instructions. If it
is an infinite loop, the pause shows where it is spinning; if the program is
just long, `F5` continues for the same amount again (or `--max-instructions`
with `--headless`).

<a id="div0"></a>
## Division by zero (`div0`, warning)

RISC-V raises no exception when dividing by zero: with the M extension the
quotient becomes −1 and the remainder is the dividend; with software division,
the result depends on the library. The program carries on with a meaningless
value. Check the divisor before dividing. With `div_by_zero = "break"` in
`[board]`, execution stops at the division.

<a id="uninit"></a>
## Uninitialized read (`uninit`, warning)

A local variable (or stack memory) was read before being assigned a value: in
C its contents are undefined, usually whatever a previous call left there.
Initialize the variable when you declare it. With `uninitialized = "break"` in
`[board]`, execution stops at the read.
