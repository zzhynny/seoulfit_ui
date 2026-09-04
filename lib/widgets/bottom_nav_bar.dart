import 'package:flutter/material.dart';
import '../theme/theme.dart';

class BottomNavItemData {
  const BottomNavItemData({required this.icon, required this.label});
  final IconData icon;
  final String label;
}

const List<BottomNavItemData> kBottomNavItems = [
  BottomNavItemData(icon: Icons.chat_bubble_outline_rounded, label: 'Chat'),
  BottomNavItemData(icon: Icons.explore_outlined, label: 'Trip'),
  BottomNavItemData(icon: Icons.qr_code_scanner_rounded, label: 'Lens'),
  BottomNavItemData(icon: Icons.calendar_today_outlined, label: 'Events'),
  BottomNavItemData(icon: Icons.manage_accounts_outlined, label: 'Profile'),
];

/// The fixed 5-tab bottom navigation bar: Chat / Trip / Lens / Events / Profile.
class BottomNavBar extends StatelessWidget {
  const BottomNavBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: AppColors.surface,
        border: Border(top: BorderSide(color: AppColors.borderAlt)),
      ),
      padding: const EdgeInsets.only(top: 12, bottom: 4, left: 16, right: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          for (var i = 0; i < kBottomNavItems.length; i++)
            _NavTab(
              data: kBottomNavItems[i],
              selected: i == currentIndex,
              onTap: () => onTap(i),
            ),
        ],
      ),
    );
  }
}

class _NavTab extends StatelessWidget {
  const _NavTab({required this.data, required this.selected, required this.onTap});

  final BottomNavItemData data;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = selected ? AppColors.primary : AppColors.textSecondary;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: SizedBox(
        width: 64,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(data.icon, size: 22, color: color),
            const SizedBox(height: 4),
            Text(
              data.label,
              style: AppTextStyles.caption.copyWith(
                color: color,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
