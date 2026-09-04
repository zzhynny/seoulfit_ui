import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import '../core/config.dart';
import '../theme/theme.dart';
import 'bottom_nav_bar.dart';
import 'figma_chrome.dart';

/// Hosts the 5-tab bottom navigation (Chat / Trip / Lens / Events / Profile)
/// around a [StatefulNavigationShell]'s indexed-stack body, so each tab's
/// scroll/state persists on switch.
class MainShell extends StatelessWidget {
  const MainShell({super.key, required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: AppConfig.showFigmaMockupChromeNotifier,
      builder: (context, showChrome, _) {
        return Scaffold(
          backgroundColor: AppColors.background,
          body: Column(
            children: [
              if (showChrome) const FakeStatusBar() else SizedBox(height: MediaQuery.of(context).padding.top),
              Expanded(child: navigationShell),
            ],
          ),
          bottomNavigationBar: SafeArea(
            top: false,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                BottomNavBar(
                  currentIndex: navigationShell.currentIndex,
                  onTap: (index) => navigationShell.goBranch(
                    index,
                    initialLocation: index == navigationShell.currentIndex,
                  ),
                ),
                if (showChrome) const FakeHomeIndicator(),
              ],
            ),
          ),
        );
      },
    );
  }
}
