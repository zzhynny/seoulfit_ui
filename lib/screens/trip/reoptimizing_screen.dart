import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/generation_pacer.dart';
import '../../widgets/loading_log_panel.dart';

class ReoptimizingScreen extends StatelessWidget {
  const ReoptimizingScreen({
    super.key,
    required this.run,
    required this.onComplete,
    required this.onFailed,
  });

  /// POST /revalidate: applies the edits, then Critic -> Repair -> Critic.
  final Future<void> Function() run;

  final VoidCallback onComplete;
  final VoidCallback onFailed;

  /// Mirrors what /revalidate actually does, in order.
  static const _stages = [
    'Applying your changes...',
    'Checking opening hours and travel times...',
    'Repairing what does not fit...',
    'Re-scoring the plan...',
  ];

  /// Shorter than generation — no RAG or planning, and the client allows 30s.
  static const _estimate = Duration(seconds: 18);

  @override
  Widget build(BuildContext context) {
    return GenerationPacer(
      stages: _stages,
      estimate: _estimate,
      run: run,
      onComplete: onComplete,
      onFailed: onFailed,
      builder: (context, progress, steps) =>
          _ReoptimizingBody(progress: progress, steps: steps),
    );
  }
}

class _ReoptimizingBody extends StatelessWidget {
  const _ReoptimizingBody({required this.progress, required this.steps});

  final double progress;
  final List<LoadingLogStep> steps;

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        showHomeIndicator: false,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
              child: Text('SeoulFit', style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Column(
                children: [
                  SizedBox(
                    width: 190,
                    height: 190,
                    child: Image.asset(companion.walkingLoadingAsset, fit: BoxFit.contain),
                  ),
                  const SizedBox(height: 32),
                  Text(
                    'Re-optimizing your itinerary based on your preferences...',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.headingSmall.copyWith(fontSize: 22),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Replacing excluded stops and re-optimizing your route',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                  ),
                  const SizedBox(height: 24),
                  GenerationProgressBar(
                    progress: progress,
                    color: AppColors.primary,
                    trackColor: AppColors.border,
                    labelStyle: AppTextStyles.caption.copyWith(
                      color: AppColors.textSecondary,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 16),
                  LoadingLogPanel(steps: steps),
                ],
              ),
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text(
                '"Tip: SeoulFit AI finds the most efficient walking and subway transfer paths dynamically."',
                textAlign: TextAlign.center,
                style: AppTextStyles.bodySmall.copyWith(color: AppColors.textSecondary.withValues(alpha: 0.8)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
