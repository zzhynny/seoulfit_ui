import 'package:flutter/material.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';

class SplashScreen extends StatelessWidget {
  const SplashScreen({super.key, required this.onGetStarted});

  final VoidCallback onGetStarted;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: FigmaDeviceFrameWrapper(
        statusBarStyle: StatusBarIconStyle.light,
        homeIndicatorColor: Colors.white,
        backgroundColor: const Color(0xFF161618),
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.asset('assets/images/splash-bg.png', fit: BoxFit.cover),
            Container(color: Colors.black.withValues(alpha: 0.4)),
            Column(
              children: [
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: Column(
                    children: [
                      Text(
                        'SeoulFit',
                        style: AppTextStyles.displayLarge.copyWith(color: Colors.white),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Your AI-powered Seoul adventure starts here',
                        textAlign: TextAlign.center,
                        style: AppTextStyles.bodyMedium.copyWith(
                          color: Colors.white.withValues(alpha: 0.9),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 48),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: PrimaryButton(label: 'Get Started', onPressed: onGetStarted),
                ),
                const SizedBox(height: 32),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
