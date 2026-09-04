import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/loading_log_panel.dart';

class ReoptimizingScreen extends StatefulWidget {
  const ReoptimizingScreen({super.key, required this.onDone});

  final VoidCallback onDone;

  @override
  State<ReoptimizingScreen> createState() => _ReoptimizingScreenState();
}

class _ReoptimizingScreenState extends State<ReoptimizingScreen> {
  @override
  void initState() {
    super.initState();
    Timer(const Duration(milliseconds: 1600), widget.onDone);
  }

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
                  const LoadingLogPanel(
                    steps: [
                      LoadingLogStep(label: 'Filling in new recommendations...', state: LoadingLogStepState.done),
                      LoadingLogStep(label: 'Checking opening hours...', state: LoadingLogStepState.active),
                      LoadingLogStep(label: 'Optimizing walking routes...', state: LoadingLogStepState.pending),
                    ],
                  ),
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
