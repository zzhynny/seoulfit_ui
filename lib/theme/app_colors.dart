import 'package:flutter/material.dart';

/// Design tokens pulled from the SeoulFit Figma file (Dev Mode MCP).
class AppColors {
  AppColors._();

  // Backgrounds
  static const Color background = Color(0xFFFCFAF7);
  static const Color backgroundAlt = Color(0xFFFAF8F5);
  static const Color composerBackground = Color(0xFFFCF9F7);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceMuted = Color(0xFFF5F3EC);
  static const Color chipBackground = Color(0xFFEAEFEA);

  // Text
  static const Color textPrimary = Color(0xFF161618);
  static const Color textSecondary = Color(0xFF4E4E52);
  static const Color textOnDark = Color(0xFFFFFFFF);

  // Borders
  static const Color border = Color(0xFFE2DED5);
  static const Color borderAlt = Color(0xFFEAE5DC);

  // Brand
  static const Color primary = Color(0xFF6B8E80); // sage green
  static const Color primaryDark = Color(0xFF5E836A);
  static const Color primaryTint = Color(0xFFEAEFEA);

  // Accent — coral/red, used for badges, alerts, missed places, error states
  static const Color accent = Color(0xFFD35D4A);
  static const Color accentDark = Color(0xFFB84A38);
  static const Color accentTint = Color(0xFFFBEAE4);

  // Chat bubbles
  static const Color bubbleBot = Color(0xFFEAEFEA);
  static const Color bubbleUser = Color(0xFF161618);

  // Status
  static const Color success = primary;
  static const Color warning = Color(0xFFE0A756);
}
