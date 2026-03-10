from workspace_onboarding_app import load_workspace_onboarding_config, parse_cli_args, resolve_runtime_options


def test_dry_run_flag_enables_both():
    args = parse_cli_args(["--dry-run"])
    options = resolve_runtime_options(args)
    assert options.dry_run_account is True
    assert options.dry_run_email is True


def test_dry_run_account_only():
    args = parse_cli_args(["--dry-run-account"])
    options = resolve_runtime_options(args)
    assert options.dry_run_account is True
    assert options.dry_run_email is False


def test_dry_run_email_only():
    args = parse_cli_args(["--dry-run-email"])
    options = resolve_runtime_options(args)
    assert options.dry_run_account is False
    assert options.dry_run_email is True


def test_load_workspace_onboarding_config_parses_groups(monkeypatch):
    monkeypatch.setenv("KOS_API_BASE_URL", "http://example.test")
    monkeypatch.setenv("KOS_API_TOKEN", "token")
    monkeypatch.setenv("GOOGLE_WORKSPACE_DOMAIN", "kwartzlab")
    monkeypatch.setenv("GOOGLE_WORKSPACE_GROUPS", "members@kwartzlab.ca,tooling@kwartzlab.ca board@kwartzlab.ca")
    cfg = load_workspace_onboarding_config()
    assert cfg.google_workspace_groups == [
        "members@kwartzlab.ca",
        "tooling@kwartzlab.ca",
        "board@kwartzlab.ca",
    ]
