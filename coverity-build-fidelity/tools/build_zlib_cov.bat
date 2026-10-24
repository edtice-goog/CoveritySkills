@echo off
REM COVERITY arm: same MSVC environment, same inner build script, wrapped in
REM cov-build. Only the wrapper differs -- that is the whole experiment.
REM
REM Required: ZLIB_SRC   (see zlib_build_inner.bat)
REM           COV_BIN    <coverity-install>\bin
REM Optional: VCVARS     path to vcvars64.bat, if not the default below
REM           WORK       scratch dir for the config and idir (default %TEMP%\cov-zlib)
setlocal
if not defined VCVARS set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo [FATAL] vcvars not found at "%VCVARS%". Set VCVARS to your vcvars64.bat.
  exit /b 1
)
if not defined COV_BIN (
  echo [FATAL] COV_BIN is not set. Point it at your Coverity bin directory, e.g.
  echo         set "COV_BIN=C:\coverity\cov-analysis-win64-VERSION\bin"
  exit /b 1
)
if not exist "%COV_BIN%\cov-build.exe" (
  echo [FATAL] cov-build.exe not found under "%COV_BIN%".
  exit /b 1
)
if not defined WORK set "WORK=%TEMP%\cov-zlib"

call "%VCVARS%" >nul || exit /b 1

set "IDIR=%WORK%\idir"
set "CFG=%WORK%\cfg\coverity_config.xml"

REM Fresh config and fresh intermediate directory every run (rules 6 and 8).
rmdir /s /q "%WORK%" 2>nul
mkdir "%WORK%\cfg" 2>nul

echo === cov-configure (msvc: a language shortcut, already template-based) ===
"%COV_BIN%\cov-configure.exe" --config "%CFG%" --msvc >nul || exit /b 1

echo === cov-build ===
"%COV_BIN%\cov-build.exe" --dir "%IDIR%" --config "%CFG%" cmd /c "%~dp0zlib_build_inner.bat" || exit /b 1

REM Assert the arm actually ran before anything downstream compares artifacts.
if not exist "%IDIR%\emit" (
  echo [FATAL] no emit directory under "%IDIR%" -- the Coverity arm did not capture.
  exit /b 1
)
echo === cov arm complete: idir at %IDIR% ===
endlocal
