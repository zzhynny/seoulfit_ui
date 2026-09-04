import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class TripFinishConfirmScreen extends StatelessWidget {
  const TripFinishConfirmScreen({
    super.key,
    required this.onSeeRecap,
    required this.onNotYet,
    required this.onBack,
  });

  final VoidCallback onSeeRecap;
  final VoidCallback onNotYet;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    return Column(
      children: [
        Container(
          decoration: const BoxDecoration(border: Border(bottom: BorderSide(color: AppColors.border))),
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          child: Row(
            children: [
              GestureDetector(onTap: onBack, child: const Icon(Icons.chevron_left, size: 20)),
              Expanded(
                child: Text('SeoulFit', textAlign: TextAlign.center, style: AppTextStyles.headingSmall.copyWith(fontSize: 20)),
              ),
              const SizedBox(width: 20),
            ],
          ),
        ),
        Expanded(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(height: 180, child: Image.asset(companion.completeAsset, fit: BoxFit.contain)),
                  const SizedBox(height: 20),
                  Text('Ready to finish your trip?', style: AppTextStyles.headingMedium.copyWith(fontSize: 28)),
                  const SizedBox(height: 12),
                  Text(
                    "We'll put together your Trip Recap — comparing what was planned with what you actually visited.",
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: Column(
            children: [
              PrimaryButton(label: 'See My Trip Recap', onPressed: onSeeRecap),
              TextButton(
                onPressed: onNotYet,
                child: Text(
                  'Not yet',
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary, fontWeight: FontWeight.w600, decoration: TextDecoration.underline),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
