#!/usr/bin/env bash
#
# hello.sh — The simplest example. Writes its own log file using job_logger.sh.
#
set -euo pipefail

# Load the shared bash log helper (SHARED_LIB env var or project layout).
source "${SHARED_LIB:-$(dirname "$0")/../shared_lib}/job_logger.sh"
jl_init   # writes header, automatically closes the footer on EXIT

jl_info "Hello! This is an example scheduler script."
jl_out "Running user      : $(whoami)"
jl_out "Working directory : $(pwd)"
jl_event greeting "hello world"
jl_metric runs 1
jl_info "Done"
