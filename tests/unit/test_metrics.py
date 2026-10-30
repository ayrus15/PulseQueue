from __future__ import annotations

from pulsequeue.observability.metrics import _formatHistogram


def testFormatHistogramWithNoSamples() -> None:
    text = _formatHistogram("pulsequeue_test_seconds", "help text", [])
    assert 'pulsequeue_test_seconds_bucket{le="+Inf"} 0' in text
    assert "pulsequeue_test_seconds_sum 0" in text
    assert "pulsequeue_test_seconds_count 0" in text


def testFormatHistogramBucketsAreCumulative() -> None:
    text = _formatHistogram("pulsequeue_test_seconds", "help", [0.01, 0.2, 0.6, 40.0])
    lines = text.splitlines()

    def bucketValue(le: str) -> int:
        for line in lines:
            if f'le="{le}"' in line:
                return int(line.rsplit(" ", 1)[1])
        raise AssertionError(f"no bucket for le={le}")

    assert bucketValue("0.05") == 1  # only 0.01
    assert bucketValue("0.25") == 2  # 0.01, 0.2
    assert bucketValue("1.0") == 3  # 0.01, 0.2, 0.6
    assert bucketValue("+Inf") == 4  # all, including the 40.0 outlier


def testFormatHistogramSumAndCount() -> None:
    text = _formatHistogram("pulsequeue_test_seconds", "help", [1.0, 2.0, 3.0])
    assert "pulsequeue_test_seconds_sum 6.0" in text
    assert "pulsequeue_test_seconds_count 3" in text
