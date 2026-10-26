@echo off
setlocal enabledelayedexpansion
rem Locate STM32_Programmer_CLI.exe: CubeIDE bundled plugin (version-agnostic), then legacy standalone.
set "CLI="
for /d %%D in ("E:\STM32\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.cubeprogrammer.win32_*") do (
  if exist "%%D\tools\bin\STM32_Programmer_CLI.exe" set "CLI=%%D\tools\bin\STM32_Programmer_CLI.exe"
)
if not defined CLI if exist "E:\STM32CubePrg-W64\bin\STM32_Programmer_CLI.exe" set "CLI=E:\STM32CubePrg-W64\bin\STM32_Programmer_CLI.exe"
if not defined CLI (
  echo [ERROR] STM32_Programmer_CLI.exe not found.
  echo         Checked CubeIDE plugins and E:\STM32CubePrg-W64\bin\
  exit /b 1
)
"%CLI%" %*
