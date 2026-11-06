# Changelog

## 0.1.1
- Fixed Python dependency resolution by pinning the Redis Python client to 5.2.1, compatible with the Celery 5.5.3 / Kombu 5.5.x dependency range.
- Fixed release packaging so ZIP contents extract directly into the repository root, without an extra enclosing `everguide/` directory.
- No database reset or destructive volume operation is required.

## 0.1.0
- Initial local Docker development foundation.
