@echo off
REM Stands in for the OFFICIAL build: same recipe, different working directory,
REM mimicking a CI agent workspace. Used to test whether the build path leaks
REM into the shipped artifact -- and whether path-length change breaks the
REM offset alignment the region algebra depends on.
REM
REM Required: CI_SRC   a SECOND zlib checkout at a deliberately CI-shaped path.
REM                    The default is short on purpose: the experiment is
REM                    whether a path LENGTH change breaks offset alignment.
REM Optional: VCVARS   path to vcvars64.bat, if not the default below
setlocal
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo [FATAL] vcvars not found at "%VCVARS%". Set VCVARS to your vcvars64.bat.
  exit /b 1
)
call "%VCVARS%" >nul || exit /b 1

if not defined CI_SRC set "CI_SRC=C:\a\1\s\zlib"
if not exist "%CI_SRC%\CMakeLists.txt" (
  echo [FATAL] "%CI_SRC%" does not look like a zlib checkout ^(no CMakeLists.txt^).
  exit /b 1
)

set "SRC=%CI_SRC%"
set "BLD=%SRC%\build-fid"
rmdir /s /q "%BLD%" 2>nul
cmake -S "%SRC%" -B "%BLD%" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >nul || exit /b 1
cmake --build "%BLD%" || exit /b 1
echo === CI-path build complete ===
endlocal
