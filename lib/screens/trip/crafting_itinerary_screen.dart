import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/generation_pacer.dart';
import '../../widgets/loading_log_panel.dart';

class CraftingItineraryScreen extends StatelessWidget {
  const CraftingItineraryScreen({
    super.key,
    required this.run,
    required this.onComplete,
    required this.onFailed,
    required this.onBackToChat,
  });

  /// Sends the confirming chat turn, which is what builds the itinerary.
  final Future<void> Function() run;

  final VoidCallback onComplete;
  final VoidCallback onFailed;

  /// An escape while the planner works. The turn keeps running on the
  /// backend, so coming back to the Trip tab still finds the finished plan.
  final VoidCallback onBackToChat;

  /// The backend's real pipeline: handle_confirm collects the answers,
  /// retrieve runs RAG over the course corpus, plan builds the days, and
  /// critic_repair scores and repairs them. Naming the actual stages means a
  /// long wait at least says what it is waiting on.
  static const _stages = [
    'Reading your answers...',
    "Searching Seoul's course library...",
    'Building your day-by-day plan...',
    "Checking the days are actually doable...",
    'Adding SeoulFit tips...',
  ];

  /// Measured at ~71s against a warm backend. Only a pacing hint — the pacer
  /// caps below 100% and waits for the real response however long it takes.
  static const _estimate = Duration(seconds: 71);

  @override
  Widget build(BuildContext context) {
    return GenerationPacer(
      stages: _stages,
      estimate: _estimate,
      run: run,
      onComplete: onComplete,
      onFailed: onFailed,
      builder: (context, progress, steps) =>
          _CraftingBody(progress: progress, steps: steps, onBackToChat: onBackToChat),
    );
  }
}

class _CraftingBody extends StatelessWidget {
  const _CraftingBody({
    required this.progress,
    required this.steps,
    required this.onBackToChat,
  });

  final double progress;
  final List<LoadingLogStep> steps;
  final VoidCallback onBackToChat;

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        showHomeIndicator: false,
        child: SingleChildScrollView(
          child: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    SizedBox(
                      width: 36,
                      height: 36,
                      child: Image.asset(companion.portraitAsset, fit: BoxFit.contain),
                    ),
                    Text('SeoulFit', style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
                    const SizedBox(width: 36),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Stack(
                  children: [
                    ClipRRect(
                      borderRadius: BorderRadius.circular(24),
                      child: SizedBox(
                        height: 248,
                        width: double.infinity,
                        child: Image.asset('assets/images/crafting-palace.png', fit: BoxFit.cover),
                      ),
                    ),
                    Positioned(
                      top: 16,
                      right: 16,
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(30)),
                        child: Text(
                          'AUTUMN TRIP',
                          style: AppTextStyles.caption.copyWith(color: AppColors.accent, fontWeight: FontWeight.w700),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 0),
                child: Column(
                  children: [
                    Text(
                      'Crafting your perfect Seoul adventure',
                      textAlign: TextAlign.center,
                      style: AppTextStyles.headingMedium.copyWith(fontSize: 28),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      'We are curating an autumnal journey tailored to your interests and dining preferences.',
                      textAlign: TextAlign.center,
                      style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 20, 24, 8),
                child: GenerationProgressBar(
                  progress: progress,
                  color: AppColors.primary,
                  trackColor: AppColors.border,
                  labelStyle: AppTextStyles.caption.copyWith(
                    color: AppColors.textSecondary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(24, 8, 24, 16),
                child: LoadingLogPanel(steps: steps),
              ),
              TextButton.icon(
                onPressed: onBackToChat,
                icon: const Icon(Icons.chevron_left, size: 18),
                label: const Text('Back to Chat'),
                style: TextButton.styleFrom(
                  foregroundColor: AppColors.textSecondary,
                  textStyle: AppTextStyles.bodySmall
                      .copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(
                  '"Tip: You can instantly translate local signage using your camera scanner."',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.bodySmall.copyWith(color: AppColors.textSecondary.withValues(alpha: 0.8)),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
