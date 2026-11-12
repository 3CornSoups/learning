"""Compatibility entry; all options now use the unified crawler."""
from douyin_crawler.runtime import main

if __name__ == '__main__':
    raise SystemExit(main())
