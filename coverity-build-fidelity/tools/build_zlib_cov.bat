@echo off
REM COVERITY arm: same MSVC environment, same inner build script, wrapped in
REM cov-build. Only the wrapper differs -- that is the whole experiment.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul

set "COV=C:\Coverity\cov-analysis-win64-2026.3.0\bin"
set "WORK=C:\Users\EdTice\AppData\Local\Temp\claude\C--Data-CoveritySkills\9e9f98f8-062a-4d24-8d72-9347687e6c95\scratchpad\cov-zlib"
set "IDIR=%WORK%\idir"
set "CFG=%WORK%\cfg\coverity_config.xml"

rmdir /s /q "%WORK%" 2>nul
mkdir "%WORK%\cfg" 2>nul

echo === cov-configure (msvc) ===
"%COV%\cov-configure.exe" --config "%CFG%" --msvc >nul || exit /b 1

echo === cov-build ===
"%COV%\cov-build.exe" --dir "%IDIR%" --config "%CFG%" cmd /c "%~dp0zlib_build_inner.bat" || exit /b 1
echo === cov arm complete ===
endlocal
