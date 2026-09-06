import 'dart:async';

import 'package:flutter/material.dart';

import 'loading_log_panel.dart';

/// Paces a progress display against a backend call that reports no progress
/// of its own.
///
/// The confirm turn runs retrieval, the planner and critic-repair inside a
/// single blocking POST — there are no events to subscribe to — so the only
/// honest thing to show is an estimate. Two rules keep it from lying:
///
///  * it never reaches 100% until the call actually returns, capping at
///    [_ceiling] however long it takes, and
///  * it never finishes early. The screen used to fire after a fixed 1.8s
///    timer and then sit at its end state for the remaining ~70s, which read
///    as a hang.
///
/// Running past the estimate is normal, not an error: the call is allowed
/// 180s. The last stage simply stays active.
class GenerationPacer extends StatefulWidget {
  const GenerationPacer({
    super.key,
    required this.stages,
    required this.estimate,
    required this.run,
    required this.onComplete,
    required this.onFailed,
    required this.builder,
  });

  /// Stage labels, in the order the backend actually works through them.
  final List<String> stages;

  /// Roughly how long the call takes when it is behaving.
  final Duration estimate;

  /// The work. Started once, on first build.
  final Future<void> Function() run;

  final VoidCallback onComplete;

  /// Called instead of [onComplete] when [run] throws — a failed generation
  /// must not leave the traveller on a spinner.
  final VoidCallback onFailed;

  final Widget Function(
    BuildContext context,
    double progress,
    List<LoadingLogStep> steps,
  ) builder;

  @override
  State<GenerationPacer> createState() => _GenerationPacerState();
}

class _GenerationPacerState extends State<GenerationPacer> {
  /// Highest fraction shown while the call is still in flight.
  static const _ceiling = 0.95;

  static const _tick = Duration(milliseconds: 120);

  /// Accumulated from the ticker rather than read off a Stopwatch, so time
  /// here is the same clock the framework drives — which also makes the
  /// pacing testable, since a real Stopwatch ignores a test's fake clock.
  Duration _elapsed = Duration.zero;

  Timer? _timer;
  bool _finished = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(_tick, (_) {
      if (!mounted || _finished) return;
      setState(() => _elapsed += _tick);
    });
    _start();
  }

  Future<void> _start() async {
    try {
      await widget.run();
      if (!mounted) return;
      // Nothing left to pace — a ticker that keeps firing holds the screen
      // permanently un-settled.
      _timer?.cancel();
      _timer = null;
      setState(() => _finished = true);
      // A beat at 100% so the bar lands rather than cutting away mid-fill.
      await Future<void>.delayed(const Duration(milliseconds: 350));
      if (mounted) widget.onComplete();
    } catch (_) {
      _timer?.cancel();
      _timer = null;
      if (mounted) widget.onFailed();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  double get _progress {
    if (_finished) return 1;
    if (widget.estimate.inMilliseconds <= 0) return _ceiling;
    final fraction =
        _elapsed.inMilliseconds / widget.estimate.inMilliseconds;
    return fraction.clamp(0.0, _ceiling);
  }

  List<LoadingLogStep> _steps(double progress) {
    final count = widget.stages.length;
    if (count == 0) return const [];
    // The final stage stays active until the call returns, so a slow run
    // shows work still happening rather than a finished-looking list.
    final active = _finished
        ? count
        : (progress * count).floor().clamp(0, count - 1);

    return [
      for (var i = 0; i < count; i++)
        LoadingLogStep(
          label: widget.stages[i],
          state: i < active
              ? LoadingLogStepState.done
              : i == active
                  ? LoadingLogStepState.active
                  : LoadingLogStepState.pending,
        ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final progress = _progress;
    return widget.builder(context, progress, _steps(progress));
  }
}

/// A thin progress bar with its percentage beside it.
class GenerationProgressBar extends StatelessWidget {
  const GenerationProgressBar({
    super.key,
    required this.progress,
    required this.color,
    required this.trackColor,
    required this.labelStyle,
  });

  final double progress;
  final Color color;
  final Color trackColor;
  final TextStyle labelStyle;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: progress),
              duration: const Duration(milliseconds: 250),
              curve: Curves.easeOut,
              builder: (context, value, _) => LinearProgressIndicator(
                value: value,
                minHeight: 6,
                backgroundColor: trackColor,
                valueColor: AlwaysStoppedAnimation<Color>(color),
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        SizedBox(
          width: 38,
          child: Text('${(progress * 100).round()}%',
              textAlign: TextAlign.right, style: labelStyle),
        ),
      ],
    );
  }
}
