import 'package:flutter/foundation.dart';

/// App-wide runtime configuration flags.
class AppConfig {
  AppConfig._();

  /// When true, screens render the baked-in Figma mockup chrome (fake iOS
  /// status bar + home-indicator bar + device corner radius) so screenshots
  /// can be pixel-compared against the Figma frames directly.
  ///
  /// When false (default), screens use the real device SafeArea / system UI
  /// instead.
  ///
  /// This is a [ValueNotifier] (not a plain const) specifically so it can be
  /// flipped live at runtime — see [FigmaChromeToggleButton] — without a
  /// hot restart, which matters when testing on web where there's no real
  /// device status bar/home indicator to compare against.
  static final ValueNotifier<bool> showFigmaMockupChromeNotifier =
      ValueNotifier<bool>(false);

  static bool get showFigmaMockupChrome => showFigmaMockupChromeNotifier.value;

  static void toggleFigmaMockupChrome() {
    showFigmaMockupChromeNotifier.value = !showFigmaMockupChromeNotifier.value;
  }
}
