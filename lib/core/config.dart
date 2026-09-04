/// App-wide static configuration flags.
class AppConfig {
  AppConfig._();

  /// When true, screens render the baked-in Figma mockup chrome (fake iOS
  /// status bar + home-indicator bar + device corner radius) so screenshots
  /// can be pixel-compared against the Figma frames directly.
  ///
  /// When false (default), screens use the real device SafeArea / system UI
  /// instead.
  static const bool showFigmaMockupChrome = false;
}
