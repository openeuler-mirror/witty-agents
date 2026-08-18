"""Shared BugKey to BugType mapping."""

BUG_KEY_TO_TYPE: dict[str, str] = {
    "BUG: kernel NULL pointer dereference": "null_pointer",
    "BUG: unable to handle kernel NULL pointer dereference at": "null_pointer",
    "Unable to handle kernel NULL pointer dereference at virtual address": "null_pointer",
    "Unable to handle kernel NULL pointer dereference": "null_pointer",
    "BUG: unable to handle kernel paging request at": "page_fault",
    "BUG: unable to handle page fault for address:": "page_fault",
    "Unable to handle kernel paging request": "page_fault",
    "BUG: stack guard page was hit": "stack_overflow",
    "BUG: Bad page map in process": "memory_corruption",
    "BUG: Bad page state in process": "memory_corruption",
    "general protection fault:": "general_protection",
    "general protection fault,": "general_protection",
    "invalid opcode": "invalid_opcode",
    "kernel BUG at": "kernel_bug",
    "NMI watchdog: Watchdog detected hard LOCKUP": "hard_lockup",
    "Watchdog detected hard LOCKUP": "hard_lockup",
    "double fault": "double_fault",
    "watchdog: BUG: soft lockup": "soft_lockup",
    "BUG: soft lockup": "soft_lockup",
    "WARNING: CPU:": "warning",
    "kernel tried to execute NX-protected page": "nx_violation",
    "unable to execute userspace code": "smep_violation",
    "Corrupted page table at address": "page_table_corruption",
    "Kernel panic - not syncing:": "panic",
    "BUG: KASAN:": "kasan",
    "BUG: KFENCE:": "kfence",
    "INFO: rcu_sched": "rcu_stall",
    "INFO: rcu_preempt": "rcu_stall",
    "blocked for more than": "hung_task",
    "list_add corruption": "list_corruption",
    "list_del corruption": "list_corruption",
    "Oops:": "oops",
    "int3:": "kernel_bug",
}


def classify_kasan_subtype(line: str) -> str:
    """Classify KASAN subtypes from a bug line."""
    if "use-after-free" in line:
        return "use_after_free"
    if "out-of-bounds" in line or "slab-out-of-bounds" in line:
        return "out_of_bounds"
    if "double-free" in line:
        return "double_free"
    return "kasan"
