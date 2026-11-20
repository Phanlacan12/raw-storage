"""Test singleton có kiểm soát (R2) và thứ tự ưu tiên cấu hình (B0)."""

from __future__ import annotations

import threading

import pytest

from document_service.config import (
    AdapterProfile,
    IntentStoreKind,
    Settings,
    SettingsProvider,
    config_files,
)
from document_service.utils.logging_setup import LoggingConfigurator
from document_service.utils.singleton import SingletonMeta


class Counter(metaclass=SingletonMeta):
    """Lớp mẫu để kiểm tra hành vi singleton."""

    def __init__(self) -> None:
        """Đếm số lần khởi tạo thật."""
        self.value = 0

    def increase(self) -> int:
        """Tăng giá trị."""
        self.value += 1
        return self.value


class Outer(metaclass=SingletonMeta):
    """Singleton tạo một singleton khác trong __init__."""

    def __init__(self) -> None:
        """Tạo singleton lồng nhau."""
        self.inner = Counter()


class TestSingleton:
    """Hành vi của SingletonMeta."""

    def test_same_instance(self) -> None:
        """Hai lần khởi tạo trả về cùng một instance."""
        assert Counter() is Counter()

    def test_state_is_shared(self) -> None:
        """Trạng thái dùng chung trong một tiến trình."""
        Counter().increase()
        assert Counter().value == 1

    def test_clear_isolates_tests(self) -> None:
        """`clear()` xoá instance nên test sau không thấy trạng thái test trước."""
        Counter().increase()
        SingletonMeta.clear(Counter)
        assert Counter().value == 0

    def test_nested_creation_does_not_deadlock(self) -> None:
        """Singleton tạo singleton khác trong __init__ vẫn chạy (khóa reentrant)."""
        outer = Outer()
        assert outer.inner is Counter()

    def test_thread_safety(self) -> None:
        """Nhiều thread khởi tạo đồng thời chỉ tạo một instance."""
        SingletonMeta.clear(Counter)
        instances: list[Counter] = []

        def create() -> None:
            instances.append(Counter())

        threads = [threading.Thread(target=create) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({id(item) for item in instances}) == 1

    def test_has_instance(self) -> None:
        """`has_instance` cho biết lớp đã được khởi tạo chưa."""
        SingletonMeta.clear(Counter)
        assert SingletonMeta.has_instance(Counter) is False
        Counter()
        assert SingletonMeta.has_instance(Counter) is True

    def test_logging_configurator_resets(self) -> None:
        """LoggingConfigurator reset được để test không rò handler."""
        configurator = LoggingConfigurator()
        configurator.configure("WARNING")
        assert configurator.configured is True
        configurator.reset()
        assert configurator.configured is False


class TestConfigPrecedence:
    """Thứ tự ưu tiên: env > .env > YAML > mặc định."""

    def test_yaml_files_are_loaded(self) -> None:
        """Các file trong configs/ được nạp theo thứ tự cố định."""
        names = [path.name for path in config_files()]
        assert "app.yml" in names
        assert "resilience.yml" in names
        assert names.index("app.yml") < names.index("health.yml")

    def test_yaml_values_applied(self, settings: Settings) -> None:
        """Giá trị trong YAML được áp dụng."""
        assert settings.intent.kind is IntentStoreKind.SQLITE
        assert settings.resilience.catalog.max_attempts == 2
        assert settings.security.require_idempotency_key is True

    def test_env_overrides_yaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Biến môi trường thắng YAML."""
        monkeypatch.setenv("DS_APP__PROFILE", "openmetadata")
        monkeypatch.setenv("DS_RESILIENCE__CATALOG__MAX_ATTEMPTS", "9")
        reloaded = SettingsProvider().reload()
        assert reloaded.app.profile is AdapterProfile.OPENMETADATA
        assert reloaded.resilience.catalog.max_attempts == 9

    def test_secrets_are_not_in_yaml(self) -> None:
        """Bí mật không được commit trong configs/."""
        for path in config_files():
            content = path.read_text(encoding="utf-8")
            assert "bot_token:" not in content or 'bot_token: ""' in content
            assert "secret_key:" not in content

    def test_provider_is_singleton(self, settings: Settings) -> None:
        """Cấu hình chỉ đọc một lần cho cả tiến trình."""
        assert SettingsProvider().settings is settings

    def test_provider_reset_reloads_from_source(self) -> None:
        """`reset()` bỏ cấu hình đã nạp; lần đọc kế tiếp nạp lại từ nguồn (R2, X36)."""
        provider = SettingsProvider()
        provider.replace(Settings(profile=AdapterProfile.FAKE))
        replaced = provider.settings
        provider.reset()
        assert provider.settings is not replaced
