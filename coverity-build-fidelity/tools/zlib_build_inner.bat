@echo off
REM The build itself -- nothing else. Assumes the MSVC environment is already
REM present (vcvars called by the caller).
REM
REM Both fidelity arms invoke THIS EXACT SCRIPT: the native arm runs it
REM directly, the Coverity arm runs it under cov-build. If the two arms ran
REM different command lines, any delta would be uninterpretable -- you would be
REM measuring the script difference, not Coverity's effect.
set "SRC=C:\Data\repo-monitoring-workspace\stage3\src\zlib"
set "BLD=%SRC%\build-fid"

rmdir /s /q "%BLD%" 2>nul
cmake -S "%SRC%" -B "%BLD%" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >nul || exit /b 1
cmake --build "%BLD%" || exit /b 1
echo === inner build complete ===
