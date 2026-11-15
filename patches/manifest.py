# SPDX-License-Identifier: MIT
"""Manifest rework, the telephony fix, and optional Flurry/diagnostics edits.

The manifest is rewritten wholesale rather than edited: the stock one declares a
targetSdk that modern Android refuses to install, no
extractNativeLibs/hardwareAcceleration flags, and no legacy storage flags. Every
value the rest of the patch set depends on is written explicitly here instead of
being inherited from whatever the input happened to contain.

The telephony edit exists because the game asks the platform for the device id
and the phone number during startup. Android 10+ throws a SecurityException for
both even when READ_PHONE_STATE is granted, which kills the app before the first
frame. The method already has fallback placeholders for the "no value" case, so
we use those directly and never touch TelephonyManager.
"""

from caligo.smali import StageError

ACT = 'smali/com/com2us/caligo/WrapperActivity.smali'
WM = 'smali/com/com2us/caligo/WrapperManager.smali'
FLURRY = 'smali/com/com2us/caligo/FlurryHandler.smali'
RND = 'smali/com/com2us/caligo/WrapperRenderer.smali'

MANIFEST = '''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.com2us.caligo" android:versionCode="5" android:versionName="%(ver)s">
    <application android:debuggable="false" android:icon="@drawable/icon" android:label="@string/app_name" android:largeHeap="true" android:hardwareAccelerated="true" android:extractNativeLibs="true" android:requestLegacyExternalStorage="true" android:usesCleartextTraffic="true">
        <activity android:configChanges="keyboardHidden|orientation" android:label="@string/app_name" android:launchMode="singleTask" android:name=".WrapperActivity" android:screenOrientation="landscape" android:theme="@android:style/Theme.NoTitleBar.Fullscreen">
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>
    </application>
    <uses-sdk android:minSdkVersion="%(min)d" android:targetSdkVersion="%(tsdk)d"/>
    <uses-permission android:name="android.permission.INTERNET"/>
    <uses-permission android:name="android.permission.READ_PHONE_STATE"/>
    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE"/>
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE"/>
    <uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE"/>
    <uses-permission android:name="android.permission.VIBRATE"/>
    <uses-permission android:name="android.permission.ACCESS_WIFI_STATE"/>
    <uses-permission android:name="android.permission.CHANGE_WIFI_STATE"/>
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
</manifest>
'''

KEYLOG = '''    # diagnostics: log the mapping so a support log shows what the pad sent
    const-string v1, "Caligo"

    new-instance v2, Ljava/lang/StringBuilder;

    invoke-direct {v2}, Ljava/lang/StringBuilder;-><init>()V

    const-string v3, "%s "

    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v2, p1}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    const-string v3, " -> game key "

    invoke-virtual {v2, v3}, Ljava/lang/StringBuilder;->append(Ljava/lang/String;)Ljava/lang/StringBuilder;

    invoke-virtual {v2, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    invoke-virtual {v2}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v2

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

'''


def apply(ctx):
    tree = ctx.tree
    min_sdk = ctx.config['device']['min_sdk']
    target_sdk = ctx.config['device']['target_sdk']

    manifest = tree.read('AndroidManifest.xml')
    if 'package="com.com2us.caligo"' not in manifest:
        raise StageError('AndroidManifest.xml does not declare com.com2us.caligo - '
                         'this does not look like Caligo Chaser.')

    version = '1.0.4'
    yml = tree.read('apktool.yml')
    for line in yml.splitlines():
        if line.strip().startswith('versionName:'):
            version = line.split(':', 1)[1].strip().strip('"\'') or version
    ctx.note('input versionName is %s' % version)

    tree.write('AndroidManifest.xml',
               (MANIFEST % dict(ver=version, min=min_sdk, tsdk=target_sdk))
               .replace('\n', '\r\n'))
    ctx.note('AndroidManifest.xml rewritten: minSdk=%d targetSdk=%d' % (min_sdk, target_sdk))

    # apktool takes minSdkVersion from apktool.yml when it rebuilds; keep the two
    # in step or the manifest we just wrote is quietly overwritten.
    yml = tree.read('apktool.yml')
    out = []
    for line in yml.splitlines(True):
        if line.strip().startswith('minSdkVersion:'):
            line = '  minSdkVersion: %d\n' % min_sdk
        out.append(line)
    tree.write('apktool.yml', ''.join(out))

    # ---------------------------------------------------------- telephony
    tree.patch(WM, '''    .line 748
    sget-object v0, Lcom/com2us/caligo/WrapperManager;->telephonyManager:Landroid/telephony/TelephonyManager;

    invoke-virtual {v0}, Landroid/telephony/TelephonyManager;->getDeviceId()Ljava/lang/String;

    move-result-object v0

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->UDID:Ljava/lang/String;

    .line 749
    sget-object v0, Lcom/com2us/caligo/WrapperManager;->UDID:Ljava/lang/String;

    if-nez v0, :cond_0

    .line 750
    const-string v0, "NULLERROR"

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->UDID:Ljava/lang/String;

    .line 751
    :cond_0
    sget-object v0, Lcom/com2us/caligo/WrapperManager;->telephonyManager:Landroid/telephony/TelephonyManager;

    invoke-virtual {v0}, Landroid/telephony/TelephonyManager;->getLine1Number()Ljava/lang/String;

    move-result-object v0

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->PHONENUMBER:Ljava/lang/String;

    .line 752
    sget-object v0, Lcom/com2us/caligo/WrapperManager;->PHONENUMBER:Ljava/lang/String;

    if-nez v0, :cond_1

    .line 753
    const-string v0, "01000000000"

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->PHONENUMBER:Ljava/lang/String;

    .line 754
    :cond_1
    return-void''', '''    .line 748
    # Android 10+ throws SecurityException for getDeviceId()/getLine1Number(),
    # granted permission or not. Use the placeholders the original falls back to.
    const-string v0, "NULLERROR"

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->UDID:Ljava/lang/String;

    const-string v0, "01000000000"

    sput-object v0, Lcom/com2us/caligo/WrapperManager;->PHONENUMBER:Ljava/lang/String;

    return-void''')
    ctx.note('telephony: device id / phone number now use placeholders')

    # ------------------------------------------------------------- flurry
    if ctx.config['patches']['disable_flurry']:
        tree.patch(ACT, '''    .line 152
    const-string v0, "RIDN6TAXIDJAT7B2R5FT"

    invoke-static {p0, v0}, Lcom/flurry/android/FlurryAgent;->onStartSession(Landroid/content/Context;Ljava/lang/String;)V
''', '''    .line 152
    # analytics disabled: the endpoint has been dead for years
''')
        tree.patch(ACT, '''    .line 157
    invoke-static {p0}, Lcom/flurry/android/FlurryAgent;->onEndSession(Landroid/content/Context;)V
''', '''    .line 157
    # analytics disabled
''')
        tree.patch(FLURRY, '''    .line 29
    :cond_0
    invoke-static {p0, v0}, Lcom/flurry/android/FlurryAgent;->onEvent(Ljava/lang/String;Ljava/util/Map;)V
''', '''    .line 29
    :cond_0
    # analytics disabled
''')
        ctx.note('analytics disabled (3 call sites)')

    # -------------------------------------------------------- diagnostics
    if ctx.config['patches']['diagnostics']:
        tree.patch(ACT, '''    .prologue
    const/16 v8, 0x80

    .line 81
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V''',
                   '''    .prologue
    const/16 v8, 0x80

    const-string v0, "Caligo"

    const-string v1, "onCreate begin"

    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    .line 81
    invoke-super {p0, p1}, Landroid/app/Activity;->onCreate(Landroid/os/Bundle;)V''')
        tree.patch(ACT, '''    .line 145
    invoke-direct {p0, v0}, Lcom/com2us/caligo/WrapperActivity;->setEditTextTextChangedListener(Landroid/widget/EditText;)V

    .line 146
    return-void''',
                   '''    .line 145
    invoke-direct {p0, v0}, Lcom/com2us/caligo/WrapperActivity;->setEditTextTextChangedListener(Landroid/widget/EditText;)V

    const-string v0, "Caligo"

    const-string v1, "onCreate end"

    invoke-static {v0, v1}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    .line 146
    return-void''')
        tree.patch(RND, '''    .locals 1
    .param p1, "gl"    # Ljavax/microedition/khronos/opengles/GL10;
    .param p2, "config"    # Ljavax/microedition/khronos/egl/EGLConfig;

    .prologue
    .line 41
    iget-object v0, p0, Lcom/com2us/caligo/WrapperRenderer;->wrapperManager:Lcom/com2us/caligo/WrapperManager;

    invoke-virtual {v0}, Lcom/com2us/caligo/WrapperManager;->initialize()V

    .line 42
    return-void''',
                   '''    .locals 3
    .param p1, "gl"    # Ljavax/microedition/khronos/opengles/GL10;
    .param p2, "config"    # Ljavax/microedition/khronos/egl/EGLConfig;

    .prologue
    .line 41
    const-string v1, "Caligo"

    const-string v2, "onSurfaceCreated -> nativeInit"

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    iget-object v0, p0, Lcom/com2us/caligo/WrapperRenderer;->wrapperManager:Lcom/com2us/caligo/WrapperManager;

    invoke-virtual {v0}, Lcom/com2us/caligo/WrapperManager;->initialize()V

    const-string v1, "Caligo"

    const-string v2, "nativeInit returned"

    invoke-static {v1, v2}, Landroid/util/Log;->i(Ljava/lang/String;Ljava/lang/String;)I

    .line 42
    return-void''')
        for tag, line in (('down', '487'), ('up', '498')):
            tree.patch(ACT, '''    .line %s
    :cond_1
    invoke-virtual {p0, p1}, Lcom/com2us/caligo/WrapperActivity;->getGameKeyCode(I)I

    move-result v0

    .line %s
    .local v0, "key":I
    if-eq v0, v4, :cond_2''' % (line, str(int(line) + 1)),
                       '''    .line %s
    :cond_1
    invoke-virtual {p0, p1}, Lcom/com2us/caligo/WrapperActivity;->getGameKeyCode(I)I

    move-result v0

    .line %s
    .local v0, "key":I
%s    if-eq v0, v4, :cond_2''' % (line, str(int(line) + 1), KEYLOG % ('key' + tag)))
        ctx.note('diagnostics: startup and key-mapping breadcrumbs added')
