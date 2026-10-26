

from trajectory_windows import TrajectoryWindows


class RollingTrajectoryWindows:
    def __init__(self, sample_ms, window_ms, step_ms, *, max_gap_ms=None):
        if (type(step_ms) is not int or not 0 < step_ms <= window_ms
                or window_ms % step_ms or step_ms % sample_ms):
            raise ValueError("step_ms must divide window_ms and be a multiple of sample_ms.")
        self.step_ms = step_ms
        self.builders = [
            TrajectoryWindows(sample_ms, window_ms, alignment_ms=phase,
                              max_gap_ms=max_gap_ms)
            for phase in range(0, window_ms, step_ms)
        ]
        self.output_count = 0

    def __getattr__(self, name):

        return getattr(self.builders[0], name)

    @property
    def counts(self):
        return {**self.builders[0].counts, "windows": self.output_count}

    def _collect(self, groups):
        windows = []
        for group in groups:
            for window in group:

                if window["window_start_ms"] < 0:
                    continue
                window["window_step_ms"] = self.step_ms
                window["window_id"] += (
                    f":rolling-{window['window_start_ms']}-{window['window_end_ms']}"
                )
                windows.append(window)
        windows.sort(key=lambda window: (window["window_end_ms"], window["target_id"]))
        self.output_count += len(windows)
        return windows

    def feed(self, event):
        return self._collect(builder.feed(event) for builder in self.builders)

    def finish(self):
        return self._collect(builder.finish() for builder in self.builders)
