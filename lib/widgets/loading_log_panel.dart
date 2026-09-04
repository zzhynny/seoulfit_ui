import 'package:flutter/material.dart';
import '../theme/theme.dart';

class LoadingLogStep {
  const LoadingLogStep({required this.label, required this.state});
  final String label;
  final LoadingLogStepState state;
}

enum LoadingLogStepState { done, active, pending }

class LoadingLogPanel extends StatelessWidget {
  const LoadingLogPanel({super.key, required this.steps});

  final List<LoadingLogStep> steps;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        children: [
          for (var i = 0; i < steps.length; i++) ...[
            if (i > 0) const SizedBox(height: 10),
            _StepRow(step: steps[i]),
          ],
        ],
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.step});

  final LoadingLogStep step;

  @override
  Widget build(BuildContext context) {
    final pending = step.state == LoadingLogStepState.pending;
    return Opacity(
      opacity: pending ? 0.5 : 1,
      child: Row(
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: switch (step.state) {
              LoadingLogStepState.done =>
                const Icon(Icons.check_circle, size: 14, color: AppColors.primary),
              LoadingLogStepState.active => const _PulsingDot(),
              LoadingLogStepState.pending => Container(
                  width: 10,
                  height: 10,
                  decoration: const BoxDecoration(
                    color: AppColors.border,
                    shape: BoxShape.circle,
                  ),
                ),
            },
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              step.label,
              style: AppTextStyles.bodySmall.copyWith(
                fontWeight: step.state == LoadingLogStepState.pending
                    ? FontWeight.w400
                    : FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PulsingDot extends StatefulWidget {
  const _PulsingDot();

  @override
  State<_PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<_PulsingDot> with SingleTickerProviderStateMixin {
  late final AnimationController _controller =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 800))
        ..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween(begin: 0.3, end: 1.0).animate(_controller),
      child: Container(
        width: 10,
        height: 10,
        decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
      ),
    );
  }
}
