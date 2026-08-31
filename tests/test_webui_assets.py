from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "src" / "meetingkit" / "webui"


def test_webui_assets_are_split_and_wired():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    css = WEBUI / "styles.css"
    javascript = WEBUI / "app.js"

    assert css.exists()
    assert javascript.exists()
    assert '<link rel="stylesheet" href="styles.css">' in html
    assert '<script src="app.js"></script>' in html


def test_home_contains_guide_changelog_and_version():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")

    assert 'id="guideOverlay"' in html
    assert 'id="changelogOverlay"' in html
    assert "v0.1.6" in html
    assert 'data-view-panel="minutes"' in html


def test_editor_has_complete_heading_table_and_delete_controls():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    javascript = (WEBUI / "app.js").read_text(encoding="utf-8")
    css = (WEBUI / "styles.css").read_text(encoding="utf-8")

    for level in range(1, 7):
        assert f'<option value="h{level}">' in html
    for action in ("addRow", "deleteRow", "addColumn", "deleteColumn"):
        assert f'data-table-action="{action}"' in html
    assert 'id="deleteOverlay"' in html
    assert "delete_session" in javascript
    assert "normalizeLegacyTableLines" in javascript
    assert 'tableLines.join("\\n")' in javascript
    assert "overflow-y: scroll" in css


def test_record_and_import_share_compact_progress_stack():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    css = (WEBUI / "styles.css").read_text(encoding="utf-8")

    import_stack = html.split('<div class="import-stack">', 1)[1].split("</div>\n      </div>", 1)[0]
    assert import_stack.index('id="progressMountImport"') < import_stack.index('class="process-note"')
    assert ".capture-stack, .import-stack" in css
    assert ".capture-layout, .import-layout { display: grid; grid-template-columns: var(--workflow-columns)" in css
    assert "--workflow-columns: minmax(380px, .94fr) minmax(430px, 1.06fr)" in css
    assert "#progressMountImport .progress-panel" in css
    assert ".process-note { min-height: 292px" in css


def test_windows_system_audio_is_visible_and_automatic():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    javascript = (WEBUI / "app.js").read_text(encoding="utf-8")

    assert 'id="systemField"' in html
    assert 'id="winHint"' in html
    assert "系统默认输出设备（WASAPI 自动内录）" in javascript
    assert '$("systemField").classList.remove("hidden")' in javascript
    assert 'busy || Boolean(status.is_windows)' in javascript
    assert 'classList.toggle("hidden", Boolean(status.is_windows))' not in javascript


def test_windows_microphone_test_and_default_device_label_are_wired():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    javascript = (WEBUI / "app.js").read_text(encoding="utf-8")

    assert 'id="btnMicTest"' in html
    assert 'id="micTestStatus"' in html
    assert 'id="micTestLevel"' in html
    assert "start_mic_test" in javascript
    assert "stop_mic_test" in javascript
    assert "系统默认（推荐，当前：" in javascript
    assert 'automaticGroup.label = "自动选择"' in javascript
    assert 'deviceGroup.label = "固定设备"' in javascript
    assert ".filter((name) => name !== defaultMicrophone" not in javascript


def test_minutes_editor_exposes_post_meeting_speaker_mapping():
    html = (WEBUI / "index.html").read_text(encoding="utf-8")
    javascript = (WEBUI / "app.js").read_text(encoding="utf-8")

    assert 'id="btnSpeakerMapping"' in html
    assert 'id="speakerOverlay"' in html
    assert 'id="speakerMapRows"' in html
    assert "get_speaker_mapping" in javascript
    assert "save_speaker_mapping" in javascript
    assert "replaceSpeakerLabels" in javascript


def test_packaging_includes_all_webui_assets():
    packaging_files = [
        ROOT / "scripts" / "build_macos.sh",
        ROOT / "scripts" / "build_windows.bat",
        ROOT / ".github" / "workflows" / "build.yml",
    ]

    for path in packaging_files:
        content = path.read_text(encoding="utf-8")
        assert "index.html" in content, path
        assert "styles.css" in content, path
        assert "app.js" in content, path


def test_windows_release_builds_and_requires_a_single_executable():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    windows_script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")

    assert "--windowed --onefile" in workflow
    assert "--windowed --onefile" in windows_script
    assert "if-no-files-found: error" in workflow


def test_release_builds_embed_version_metadata():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    macos_script = (ROOT / "scripts" / "build_macos.sh").read_text(encoding="utf-8")
    windows_script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")
    windows_version = (ROOT / "assets" / "version_info.txt").read_text(encoding="utf-8")

    assert '--version-file assets\\version_info.txt' in workflow
    assert '--version-file assets\\version_info.txt' in windows_script
    for content in (workflow, macos_script):
        assert "Set :CFBundleShortVersionString 0.1.6" in content
        assert "Set :CFBundleVersion 0.1.6" in content
    assert "filevers=(0, 1, 6, 0)" in windows_version
    assert "prodvers=(0, 1, 6, 0)" in windows_version
    assert "StringStruct('FileVersion', '0.1.6')" in windows_version
    assert "StringStruct('ProductVersion', '0.1.6')" in windows_version


def test_windows_release_uses_native_certificate_store():
    workflow = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    windows_script = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "truststore==0.10.4; sys_platform == 'win32'" in requirements
    assert "--hidden-import truststore._windows" in workflow
    assert "--hidden-import truststore._windows" in windows_script
    assert workflow.count("python -m pytest") == 2


def test_release_metadata_uses_github_identity_not_conversational_name():
    windows_version = (ROOT / "assets" / "version_info.txt").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    javascript = (WEBUI / "app.js").read_text(encoding="utf-8")

    assert "StringStruct('CompanyName', 'whisper2upp-max')" in windows_version
    assert "Copyright (c) 2026 whisper2upp-max" in windows_version
    assert "[@whisper2upp-max]" in readme
    for content in (windows_version, readme, javascript):
        assert "Wesley Yan" not in content
