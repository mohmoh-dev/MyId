@echo off

setlocal
set DIR=%~dp0

:: Gradle wrapper properties
set GRADLE_VERSION=7.4.2
set DIST_URL=https://services.gradle.org/distributions/gradle-%GRADLE_VERSION%-bin.zip

if not exist "%~dp0gradle-wrapper.jar" (
    echo Downloading Gradle %GRADLE_VERSION%...
    curl -L "%DIST_URL%" -o "%DIR%gradle.zip"
    echo Extracting Gradle wrapper...
    mkdir "%DIR%gradle"
    powershell -Command "Expand-Archive -Path '%DIR%gradle.zip' -DestinationPath '%DIR%gradle'"
    del "%DIR%gradle.zip"
    move "%DIR%gradle\gradle-%GRADLE_VERSION%\*" "%DIR%gradle\"
    rmdir /s /q "%DIR%gradle-%GRADLE_VERSION%"
)

java -jar "%~dp0gradle\gradle\gradle-wrapper.jar" %*