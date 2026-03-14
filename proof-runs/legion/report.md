# Android AutoRELab Report: 20260313-095648-493842

## Summary
- Artifacts discovered: 2
- Binary analyses: 1
- SWAP candidates: 3

## Top SWAPs
### SWAP-001: Potential fail-open authorization logic in check_admin_token
- Class: CWE-287-like improper authentication / fail-open decision
- Impact: high
- Confidence: 0.72
- Location: `/home/oem/android-autorelab/runs/legion/20260313-095648-493842/work/demo-inputs/swap-demo-x86_64` :: `check_admin_token` @ `00401216`
- Reachability: Authentication logic appears to reconverge success and failure conditions into a permissive result for reachable caller-controlled state.
- Evidence: 
int check_admin_token(char *role,int pin_ok)

{
  int iVar1;
  int pin_ok_local;
  char *role_local;
  int is_admin;
  
  iVar1 = strcmp(role,"admin");
  if (pin_ok == 0) {
    puts("pin failed");
  }
  if ((iVar1 == 0) || (pin_ok != 0)) {
    iVar1 = 1;
  }
  else {
    iVar1 = 0;
  }
  return iVar1;
}


- CFG summary: nodes=8 edges=12
- Remediation intent: Separate failure handling from the success path, require all auth predicates to pass, and add explicit deny-by-default returns.
- Verification tests: Add tests for invalid credentials and partial-auth states to ensure every failure path returns denial.

### SWAP-002: Potential unsafe buffer handling in vulnerable_copy
- Class: CWE-120-like stack/heap buffer misuse
- Impact: high
- Confidence: 0.67
- Location: `/home/oem/android-autorelab/runs/legion/20260313-095648-493842/work/demo-inputs/swap-demo-x86_64` :: `vulnerable_copy` @ `00401279`
- Reachability: User-controlled bytes appear to flow into unsafe string-copy primitives reachable from the analyzed binary entrypoints.
- Evidence: 
int vulnerable_copy(char *input)

{
  char *input_local;
  char buffer [16];
  
  strcpy(buffer,input);
  return (int)buffer[0];
}


- CFG summary: nodes=2 edges=2
- Remediation intent: Replace unsafe copies with length-checked APIs, validate input size before writes, and add negative-path tests for oversized data.
- Verification tests: Add unit tests with oversized strings and assert rejection or truncation without memory corruption.

### SWAP-003: Potential arithmetic-driven allocation bug in multiply_count
- Class: CWE-190-like integer overflow influencing memory allocation
- Impact: med
- Confidence: 0.58
- Location: `/home/oem/android-autorelab/runs/legion/20260313-095648-493842/work/demo-inputs/swap-demo-x86_64` :: `multiply_count` @ `004012a5`
- Reachability: External numeric fields appear to influence multiplication or size calculations before allocation or copy operations.
- Evidence: 
int multiply_count(char *count_str)

{
  int iVar1;
  void *__s;
  char *count_str_local;
  char *heap;
  int bytes;
  int count;
  
  iVar1 = atoi(count_str);
  iVar1 = iVar1 << 0xc;
  __s = malloc((long)iVar1);
  if (__s == (void *)0x0) {
    iVar1 = -1;
  }
  else {
    memset(__s,0,(long)iVar1);
    free(__s);
  }
  return iVar1;
}


- CFG summary: nodes=8 edges=12
- Remediation intent: Introduce checked arithmetic for size calculations and reject values that overflow or exceed expected bounds before allocation.
- Verification tests: Add boundary tests covering large count values and assert checked-failure behavior instead of wrapped sizes.

## Appendix
- Tool logs: `logs/`
- Prompt logs: `prompts/`
- Artifact JSON: `artifacts/`
