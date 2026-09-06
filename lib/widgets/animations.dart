import 'package:flutter/material.dart';

/// Motion design tokens for SeoulFit.
///
/// Centralizes durations and curves so every screen animates with the same
/// rhythm. Durations follow the micro-interaction guideline (150-300ms for
/// taps, slightly longer for entrances). Curves favour organic, spring-like
/// motion over linear/robotic easing.
class Motion {
  Motion._();

  // Durations
  static const Duration fast = Duration(milliseconds: 180);
  static const Duration base = Duration(milliseconds: 320);
  static const Duration slow = Duration(milliseconds: 520);

  // Stagger step between siblings in a list reveal.
  static const Duration stagger = Duration(milliseconds: 70);

  // Curves
  /// Smooth deceleration for entrances (ease-out).
  static const Curve enter = Curves.easeOutCubic;

  /// Gentle spring overshoot for signature moments (mascot, success states).
  static const Cubic spring = Cubic(0.34, 1.56, 0.64, 1.0);

  /// Quick, tactile response for press/tap feedback.
  static const Curve press = Curves.easeOut;

  /// Whether the platform requests reduced motion. When true, widgets should
  /// skip transform/opacity animation and render in their final state.
  static bool reduced(BuildContext context) =>
      MediaQuery.maybeOf(context)?.disableAnimations ?? false;
}

/// Fades and slides a child into place once, on first build.
///
/// Pass an incrementing [delay] to siblings to create a staggered reveal.
/// Honours the platform reduced-motion setting by rendering instantly.
class FadeSlideIn extends StatefulWidget {
  final Widget child;
  final Duration delay;
  final Duration duration;

  /// Vertical travel distance in logical pixels. Negative slides down-from-up.
  final double offsetY;

  /// Horizontal travel distance in logical pixels.
  final double offsetX;

  const FadeSlideIn({
    super.key,
    required this.child,
    this.delay = Duration.zero,
    this.duration = Motion.base,
    this.offsetY = 16,
    this.offsetX = 0,
  });

  @override
  State<FadeSlideIn> createState() => _FadeSlideInState();
}

class _FadeSlideInState extends State<FadeSlideIn>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: widget.duration);
  late final Animation<double> _t =
      CurvedAnimation(parent: _controller, curve: Motion.enter);

  bool _started = false;

  void _start() {
    if (_started) return;
    _started = true;
    if (Motion.reduced(context)) {
      _controller.value = 1.0;
    } else if (widget.delay == Duration.zero) {
      _controller.forward();
    } else {
      Future.delayed(widget.delay, () {
        if (mounted) _controller.forward();
      });
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _start();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _t,
      builder: (context, child) {
        final v = _t.value;
        return Opacity(
          opacity: v,
          child: Transform.translate(
            offset: Offset(
              widget.offsetX * (1 - v),
              widget.offsetY * (1 - v),
            ),
            child: child,
          ),
        );
      },
      child: widget.child,
    );
  }
}

/// Convenience: wrap each item in a list with a staggered [FadeSlideIn].
///
/// ```dart
/// Column(children: stagger(items.map(buildCard).toList()))
/// ```
List<Widget> stagger(
  List<Widget> children, {
  Duration step = Motion.stagger,
  Duration initialDelay = Duration.zero,
  double offsetY = 16,
}) {
  return List.generate(children.length, (i) {
    return FadeSlideIn(
      delay: initialDelay + step * i,
      offsetY: offsetY,
      child: children[i],
    );
  });
}

/// Wraps a child so it scales down slightly while pressed, springing back on
/// release. Adds the tactile feedback that defines a micro-interaction UI.
///
/// Use for cards, list rows, and custom buttons that aren't already a
/// Material button. Respects reduced motion by disabling the scale.
class PressableScale extends StatefulWidget {
  final Widget child;
  final VoidCallback? onTap;
  final double scale;
  final BorderRadius? borderRadius;
  final HitTestBehavior behavior;

  const PressableScale({
    super.key,
    required this.child,
    this.onTap,
    this.scale = 0.96,
    this.borderRadius,
    this.behavior = HitTestBehavior.opaque,
  });

  @override
  State<PressableScale> createState() => _PressableScaleState();
}

class _PressableScaleState extends State<PressableScale> {
  bool _pressed = false;

  void _set(bool v) {
    if (_pressed != v) setState(() => _pressed = v);
  }

  @override
  Widget build(BuildContext context) {
    final reduced = Motion.reduced(context);
    final target = (_pressed && !reduced) ? widget.scale : 1.0;
    return GestureDetector(
      behavior: widget.behavior,
      onTap: widget.onTap,
      onTapDown: (_) => _set(true),
      onTapUp: (_) => _set(false),
      onTapCancel: () => _set(false),
      child: AnimatedScale(
        scale: target,
        duration: Motion.fast,
        curve: Motion.press,
        child: widget.child,
      ),
    );
  }
}

/// Tweens an integer from 0 to [value] once, on build. Used for the Seoul Lens
/// confidence score and other "count up" reveals.
class CountUp extends StatelessWidget {
  final int value;
  final Duration duration;
  final TextStyle? style;
  final String suffix;

  const CountUp({
    super.key,
    required this.value,
    this.duration = Motion.slow,
    this.style,
    this.suffix = '',
  });

  @override
  Widget build(BuildContext context) {
    if (Motion.reduced(context)) {
      return Text('$value$suffix', style: style);
    }
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: value.toDouble()),
      duration: duration,
      curve: Motion.enter,
      builder: (context, v, _) => Text('${v.round()}$suffix', style: style),
    );
  }
}
