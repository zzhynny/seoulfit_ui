import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';

class PermissionsScreen extends StatefulWidget {
  const PermissionsScreen({super.key, required this.onContinue, required this.onBack});

  final VoidCallback onContinue;
  final VoidCallback onBack;

  @override
  State<PermissionsScreen> createState() => _PermissionsScreenState();
}

class _PermissionsScreenState extends State<PermissionsScreen> {
  bool _location = true;
  bool _camera = true;
  bool _notifications = false;

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    return Scaffold(
      backgroundColor: AppColors.background,
      body: FigmaDeviceFrameWrapper(
        child: Stack(
          children: [
            Column(
              children: [
                const SizedBox(height: 44),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: IconButton(
                      onPressed: widget.onBack,
                      icon: const Icon(Icons.chevron_left, size: 28),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Column(
                    children: [
                      SizedBox(
                        height: 60,
                        child: Image.asset(companion.portraitAsset, fit: BoxFit.contain),
                      ),
                      const SizedBox(height: 24),
                      Text(
                        'Customize Your Adventure',
                        textAlign: TextAlign.center,
                        style: AppTextStyles.headingMedium,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'Allow SeoulFit access to personalize recommendations and keep your trip running smoothly.',
                        textAlign: TextAlign.center,
                        style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Column(
                    children: [
                      _PermissionCard(
                        icon: Icons.location_on_outlined,
                        title: 'Location Access',
                        description:
                            'Find hidden local spots, culinary gems, and step-by-step subway routes near you.',
                        value: _location,
                        onChanged: (v) => setState(() => _location = v),
                      ),
                      const SizedBox(height: 14),
                      _PermissionCard(
                        icon: Icons.camera_alt_outlined,
                        title: 'Camera',
                        description:
                            'Instantly scan and translate Korean food menus, signs, and subway maps on the go.',
                        value: _camera,
                        onChanged: (v) => setState(() => _camera = v),
                      ),
                      const SizedBox(height: 14),
                      _PermissionCard(
                        icon: Icons.notifications_none,
                        title: 'Smart Notifications',
                        description:
                            'Receive dynamic schedule reminders, boarding alerts, and local weather updates.',
                        value: _notifications,
                        onChanged: (v) => setState(() => _notifications = v),
                      ),
                    ],
                  ),
                ),
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    children: [
                      PrimaryButton(label: 'Allow Access & Continue', onPressed: widget.onContinue),
                      const SizedBox(height: 8),
                      TextButton(
                        onPressed: widget.onContinue,
                        child: Text(
                          'Skip for now',
                          style: AppTextStyles.bodyMedium.copyWith(
                            color: AppColors.textSecondary,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _PermissionCard extends StatelessWidget {
  const _PermissionCard({
    required this.icon,
    required this.title,
    required this.description,
    required this.value,
    required this.onChanged,
  });

  final IconData icon;
  final String title;
  final String description;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: const BoxDecoration(
              color: AppColors.chipBackground,
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: AppColors.primary, size: 22),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: AppTextStyles.cardTitle),
                const SizedBox(height: 4),
                Text(description, style: AppTextStyles.bodySmall),
              ],
            ),
          ),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: Colors.white,
            activeTrackColor: AppColors.primary,
          ),
        ],
      ),
    );
  }
}
