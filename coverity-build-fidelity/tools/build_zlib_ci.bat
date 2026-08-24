@echo off
REM Stands in for the OFFICIAL build: same recipe, different working directory,
REM mimicking a CI agent workspace. Used to test whether the build path leaks
REM into the shipped artifact -- and whether path-length change breaks the
REM offset alignment the region algebra depends on.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
set "SRC=C:\a\1\s\zlib"
set "BLD=%SRC%\build-fid"
rmdir /s /q "%BLD%" 2>nul
cmake -S "%SRC%" -B "%BLD%" -G Ninja -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 >nul || exit /b 1
cmake --build "%BLD%" || exit /b 1
echo === CI-path build complete ===
endlocal
