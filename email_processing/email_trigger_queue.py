import argparse
import time

from email_processing.email_queue import EmailTriggerQueue


def main():
    parser = argparse.ArgumentParser(
        description="Email-driven queue for BANK RECON Playwright runs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep polling the mailbox on an interval.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Polling interval in seconds when --watch is enabled.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum unread emails to pull per poll.",
    )
    args = parser.parse_args()

    queue = EmailTriggerQueue()

    def poll_once():
        added = queue.poll_and_enqueue(max_results=args.max_results)
        if added:
            queue.wait_for_completion()

    poll_once()

    if args.watch:
        while True:
            time.sleep(args.interval)
            poll_once()


if __name__ == "__main__":
    main()
