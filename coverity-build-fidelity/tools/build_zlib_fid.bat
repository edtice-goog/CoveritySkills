@echo off
REM NATIVE arm: MSVC environment, then the shared inner build script.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
call "%~dp0zlib_build_inner.bat" || exit /b 1
endlocal
