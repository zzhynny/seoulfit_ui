import 'package:flutter/material.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';

class ErrorScreen extends StatelessWidget {
  const ErrorScreen({
    super.key,
    required this.onTryAgain,
    required this.onBackToHome,
    required this.onBack,
  });

  final VoidCallback onTryAgain;
  final VoidCallback onBackToHome;
  final VoidCallback onBack;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundAlt,
      body: FigmaDeviceFrameWrapper(
        backgroundColor: AppColors.backgroundAlt,
        child: Column(
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
            const Spacer(),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: Column(
                children: [
                  Container(
                    width: 64,
                    height: 64,
                    decoration: const BoxDecoration(color: AppColors.chipBackground, shape: BoxShape.circle),
                    alignment: Alignment.center,
                    child: Text('!', style: AppTextStyles.headingSmall.copyWith(fontSize: 24, color: AppColors.primary, fontWeight: FontWeight.w700)),
                  ),
                  const SizedBox(height: 24),
                  Text(
                    'A wild glitch appeared!',
                    textAlign: TextAlign.center,
                    style: AppTextStyles.headingSmall.copyWith(fontSize: 22, color: const Color(0xFF2D312E)),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    "Our guide got a little turned around. We're working on finding the right trail—please check your connection or try again.",
                    textAlign: TextAlign.center,
                    style: AppTextStyles.bodyMedium.copyWith(color: const Color(0xFF6B7280)),
                  ),
                ],
              ),
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: PrimaryButton(label: 'Try Again', onPressed: onTryAgain),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 20),
              child: TextButton(
                onPressed: onBackToHome,
                child: Text('Back to Home', style: AppTextStyles.bodyMedium.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w500)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
