# -*- mode: python ; coding: utf-8 -*-

import os

block_cipher = None
app_dir = os.path.abspath('.')

a = Analysis(
    ['main.py'],
    pathex=[app_dir],
    binaries=[],
    datas=[
        ('icon_256.png', '.'),
    ],
    hiddenimports=[
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc',
        'PySide6.QtPositioning',
        'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtSpatialAudio',
        'PySide6.QtSvg',
        'PySide6.QtSvgWidgets',
        'PySide6.QtTest',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtXml',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtQml',
        'PySide6.QtNetwork',
        'PySide6.QtDBus',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtPrintSupport',
        'PySide6.QtSql',
        'PySide6.QtStateMachine',
        'PySide6.QtUiTools',
        'PySide6.QtConcurrent',
        'PySide6.QtHttpServer',
        'PySide6.QtLocation',
        'PySide6.QtNetworkAuth',
        'PySide6.QtScxml',
        'PySide6.QtTextToSpeech',
        'PySide6.QtVirtualKeyboard',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='W0BCQ_Logger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='W0BCQ_Logger',
)
