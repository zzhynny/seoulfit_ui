import 'dart:async';
import 'package:flutter/material.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/loading_log_panel.dart';

class CraftingItineraryScreen extends StatefulWidget {
  const CraftingItineraryScreen({super.key, required this.onDone});

  final VoidCallback onDone;

  @override
  State<CraftingItineraryScreen> createState() => _CraftingItineraryScreenState();
}

class _CraftingItineraryScreenState extends State<CraftingItineraryScreen> {
  @override
  void initState() {
    super.initState();
    Timer(const Duration(milliseconds: 1800), widget.onDone);
  }

  @override
  Widget build(BuildContext context) {
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
                    const SizedBox(width: 36),
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
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 16),
                child: const LoadingLogPanel(
                  steps: [
                    LoadingLogStep(label: 'Mapping local autumn foliage...', state: LoadingLogStepState.done),
                    LoadingLogStep(label: 'Filtering premium vegan culinary dining...', state: LoadingLogStepState.done),
                    LoadingLogStep(label: 'Optimizing neighborhood walking routes...', state: LoadingLogStepState.pending),
                    LoadingLogStep(label: 'Assembling custom SeoulFit AI tips...', state: LoadingLogStepState.pending),
                  ],
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
