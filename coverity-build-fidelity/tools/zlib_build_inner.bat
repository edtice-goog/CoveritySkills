@echo off
REM The build itself -- nothing else. Assumes the MSVC environment is already
REM present (vcvars called by the caller).
REM
REM Both fidelity arms invoke THIS EXACT SCRIPT: the native arm runs it
REM directly, the Coverity arm runs it under cov-build. If the two arms ran
REM different command lines, any delta would be uninterpretable -- you would be
REM measuring the script difference, not Coverity's effect.
REM
REM Required:
REM   ZLIB_SRC  your zlib checkout, e.g.  set "ZLIB_SRC=C:\src\zlib"
REM
REM The build directory is ZLIB_SRC\build-fid, dedicated to this experiment so
REM an existing build tree is never touched. Every arm uses the SAME directory
REM on purpose: holding the path constant is what keeps the diff regions
REM aligned across runs.

if not defined ZLIB_SRC (
  echo [FATAL] ZLIB_SRC is not set. Point it at your zlib checkout, e.g.
  echo         set "ZLIB_SRC=C:\src\zlib"
  exit /b 1
)
if not exist "%ZLIB_SRC%\CMakeLists.txt" (
  echo [FATAL] "%ZLIB_SRC%" does not look like a zlib checkout ^(no CMakeLists.txt^).
  exit /b 1
)

set "SRC=%ZLIB_SRC%"
set "BLD=%SRC%\build-fid"

rmdir /s /q "%BLD%" 2>nul
cmake -S "%SRC%" -B "%BLD%" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >nul || exit /b 1
cmake --build "%BLD%" || exit /b 1
echo === inner build complete ===
