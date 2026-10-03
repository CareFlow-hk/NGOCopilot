from .base import run_worker


def main():
    run_worker("scheduler", {"activity_scheduler"})


if __name__ == "__main__":
    main()
