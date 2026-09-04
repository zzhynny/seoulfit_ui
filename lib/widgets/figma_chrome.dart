import 'package:flutter/material.dart';
import '../core/config.dart';
import '../theme/theme.dart';

/// Icon color for the fake status bar, matched per-screen to the Figma frame
/// it sits on (dark icons on light backgrounds, light icons on photo/dark
/// backgrounds like the Splash screen).
enum StatusBarIconStyle { dark, light }

/// Reproduces the baked-in fake iOS status bar drawn inside every Figma
/// frame (time + cellular/wifi/battery glyphs). Only rendered when
/// [AppConfig.showFigmaMockupChrome] is true.
class FakeStatusBar extends StatelessWidget {
  const FakeStatusBar({
    super.key,
    this.style = StatusBarIconStyle.dark,
    this.height = 54,
  });

  final StatusBarIconStyle style;
  final double height;

  @override
  Widget build(BuildContext context) {
    final color =
        style == StatusBarIconStyle.dark ? AppColors.textPrimary : Colors.white;
    return SizedBox(
      height: height,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('9:41', style: AppTextStyles.statusBarTime.copyWith(color: color)),
            Row(
              children: [
                Icon(Icons.signal_cellular_alt, size: 15, color: color),
                const SizedBox(width: 6),
                Icon(Icons.wifi, size: 15, color: color),
                const SizedBox(width: 6),
                Icon(Icons.battery_full, size: 18, color: color),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// Reproduces the baked-in fake home-indicator bar drawn inside every Figma
/// frame. Only rendered when [AppConfig.showFigmaMockupChrome] is true.
class FakeHomeIndicator extends StatelessWidget {
  const FakeHomeIndicator({super.key, this.color = AppColors.textPrimary});

  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 29,
      alignment: Alignment.topCenter,
      padding: const EdgeInsets.only(top: 12),
      child: Container(
        width: 134,
        height: 5,
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(AppRadii.pill),
        ),
      ),
    );
  }
}

/// Wraps a standalone (non-tab-shell) screen's body content with the Figma
/// mockup chrome (fake status bar + home indicator + device corner radius)
/// when [AppConfig.showFigmaMockupChrome] is true, or the real SafeArea /
/// system UI otherwise.
class FigmaDeviceFrameWrapper extends StatelessWidget {
  const FigmaDeviceFrameWrapper({
    super.key,
    required this.child,
    this.statusBarStyle = StatusBarIconStyle.dark,
    this.homeIndicatorColor = AppColors.textPrimary,
    this.showHomeIndicator = true,
    this.backgroundColor,
  });

  final Widget child;
  final StatusBarIconStyle statusBarStyle;
  final Color homeIndicatorColor;
  final bool showHomeIndicator;
  final Color? backgroundColor;

  @override
  Widget build(BuildContext context) {
    if (!AppConfig.showFigmaMockupChrome) {
      return SafeArea(child: child);
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadii.deviceFrame),
      child: Container(
        color: backgroundColor ?? AppColors.background,
        child: Column(
          children: [
            FakeStatusBar(style: statusBarStyle),
            Expanded(child: child),
            if (showHomeIndicator) FakeHomeIndicator(color: homeIndicatorColor),
          ],
        ),
      ),
    );
  }
}
