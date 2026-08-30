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
    assert "v0.1.0" in html
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
        assert "Set :CFBundleShortVersionString 0.1.0" in content
        assert "Set :CFBundleVersion 0.1.0" in content
    assert "filevers=(0, 1, 0, 0)" in windows_version
    assert "prodvers=(0, 1, 0, 0)" in windows_version
    assert "StringStruct('FileVersion', '0.1.0')" in windows_version
    assert "StringStruct('ProductVersion', '0.1.0')" in windows_version
