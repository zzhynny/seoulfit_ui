import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'app_colors.dart';

/// Typography tokens: DM Serif Text for headings, Manrope for body/UI text.
class AppTextStyles {
  AppTextStyles._();

  static TextStyle _serif({
    required double size,
    double height = 1.2,
    Color color = AppColors.textPrimary,
  }) {
    return GoogleFonts.dmSerifText(
      fontSize: size,
      height: height,
      color: color,
      fontWeight: FontWeight.w400,
    );
  }

  static TextStyle _sans({
    required double size,
    FontWeight weight = FontWeight.w400,
    double height = 1.5,
    Color color = AppColors.textPrimary,
  }) {
    return GoogleFonts.manrope(
      fontSize: size,
      height: height,
      color: color,
      fontWeight: weight,
    );
  }

  /// Ad-hoc body text in the UI's sans face.
  ///
  /// Exists so screens ported from the Flutter app — which called
  /// `GoogleFonts.plusJakartaSans(...)` inline at ~300 sites — can be
  /// converted one-for-one onto Manrope instead of being hand-rewritten onto
  /// the named styles below. Prefer the named styles in new code.
  static TextStyle sans({
    double fontSize = 14,
    FontWeight fontWeight = FontWeight.w400,
    Color color = AppColors.textPrimary,
    double? height,
    double? letterSpacing,
    TextDecoration? decoration,
    FontStyle? fontStyle,
  }) =>
      _sans(size: fontSize, weight: fontWeight, color: color)
          .copyWith(
            height: height,
            letterSpacing: letterSpacing,
            decoration: decoration,
            fontStyle: fontStyle,
          );

  // Headings (DM Serif Text)
  static TextStyle get displayLarge => _serif(size: 48);
  static TextStyle get headingLarge => _serif(size: 32);
  static TextStyle get headingMedium => _serif(size: 30);
  static TextStyle get headingSmall => _serif(size: 20, height: 1.3);

  // Body / UI (Manrope)
  static TextStyle get bodyLarge =>
      _sans(size: 16, weight: FontWeight.w400, height: 1.5);
  static TextStyle get bodyMedium =>
      _sans(size: 14, weight: FontWeight.w400, height: 1.5);
  static TextStyle get bodySmall =>
      _sans(size: 13, weight: FontWeight.w400, height: 1.4);
  static TextStyle get caption =>
      _sans(size: 11, weight: FontWeight.w500, color: AppColors.textSecondary);

  static TextStyle get labelUppercase => _sans(
        size: 12,
        weight: FontWeight.w600,
        color: AppColors.textSecondary,
      ).copyWith(letterSpacing: 0.4);

  static TextStyle get buttonLabel =>
      _sans(size: 16, weight: FontWeight.w700, color: AppColors.textOnDark);

  static TextStyle get cardTitle =>
      _sans(size: 15, weight: FontWeight.w700, height: 1.2);

  static TextStyle get statusBarTime =>
      _sans(size: 15, weight: FontWeight.w600);
}
