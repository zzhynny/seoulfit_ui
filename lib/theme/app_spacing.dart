/// Spacing scale observed across SeoulFit Figma frames.
class AppSpacing {
  AppSpacing._();

  static const double xs = 4;
  static const double sm = 8;
  static const double smMd = 12;
  static const double md = 14;
  static const double lg = 16;
  static const double xl = 20;
  static const double xxl = 24;
  static const double xxxl = 32;

  /// Standard horizontal screen padding.
  static const double screenPadding = 24;
}

/// Corner radii observed across SeoulFit Figma frames.
class AppRadii {
  AppRadii._();

  static const double sm = 8;
  static const double md = 12;
  static const double lg = 16;
  static const double xl = 20;
  static const double xxl = 22;
  static const double pill = 100;

  /// Baked-in device-mockup outer corner radius (Figma chrome only).
  static const double deviceFrame = 48;
}
