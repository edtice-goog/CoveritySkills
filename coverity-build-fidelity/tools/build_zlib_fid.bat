@echo off
REM NATIVE arm: MSVC environment, then the shared inner build script.
REM
REM Required: ZLIB_SRC   (see zlib_build_inner.bat)
REM Optional: VCVARS     path to vcvars64.bat, if yours is not the default below
setlocal
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo [FATAL] vcvars not found at "%VCVARS%". Set VCVARS to your vcvars64.bat.
  exit /b 1
)
call "%VCVARS%" >nul || exit /b 1
call "%~dp0zlib_build_inner.bat" || exit /b 1
endlocal
