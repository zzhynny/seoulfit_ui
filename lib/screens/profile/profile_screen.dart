import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../data/repositories/profile_repository.dart';
import '../../models/profile.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/primary_button.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({
    super.key,
    required this.onChangeCompanion,
    required this.onViewStampBook,
  });

  final VoidCallback onChangeCompanion;
  final VoidCallback onViewStampBook;

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  UserProfile? _profile;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final profile = await context.read<ProfileRepository>().fetchProfile();
    if (!mounted) return;
    setState(() => _profile = profile);
  }

  @override
  Widget build(BuildContext context) {
    final companion = context.watch<CompanionProvider>().selected;
    final profile = _profile;
    if (profile == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return SingleChildScrollView(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text('Profile', style: AppTextStyles.headingMedium.copyWith(fontSize: 26)),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: AppColors.borderAlt),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Row(
                children: [
                  SizedBox(width: 49, height: 56, child: Image.asset(companion.portraitAsset, fit: BoxFit.contain)),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(profile.name, style: AppTextStyles.cardTitle.copyWith(fontSize: 18)),
                        Container(
                          margin: const EdgeInsets.symmetric(vertical: 4),
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(color: const Color(0xFFE8EFEB), borderRadius: BorderRadius.circular(12)),
                          child: Text(profile.explorerBadge, style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w700, fontSize: 10)),
                        ),
                        Text('Companion: ${companion.displayName}', style: AppTextStyles.bodySmall),
                      ],
                    ),
                  ),
                  GestureDetector(
                    onTap: widget.onChangeCompanion,
                    child: Text('Change', style: AppTextStyles.bodyMedium.copyWith(color: AppColors.primary, fontWeight: FontWeight.w600, fontSize: 13)),
                  ),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: AppColors.borderAlt),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Column(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    decoration: BoxDecoration(color: const Color(0xFFF7F5F1), borderRadius: BorderRadius.circular(12)),
                    child: Row(
                      children: [
                        _statColumn('🐾 ${profile.stampsCollected} / ${profile.stampsTotal}', 'Stamps Collected'),
                        _statColumn('${profile.spotsVisited} Spots', 'Visited Places'),
                        _statColumn('${profile.savedRecaps} Saved', 'Trip Recaps'),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  PrimaryButton(label: 'View Stamp Book & Recaps →', onPressed: widget.onViewStampBook),
                ],
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      'MY TRAVEL PREFERENCES',
                      style: AppTextStyles.labelUppercase.copyWith(color: AppColors.primary, letterSpacing: 1.5),
                    ),
                    Text('Edit', style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w700)),
                  ],
                ),
                const SizedBox(height: 10),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: AppColors.borderAlt),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (final pref in profile.preferences)
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                          decoration: BoxDecoration(
                            color: const Color(0xFFF2F6F3),
                            border: Border.all(color: AppColors.primary.withValues(alpha: 0.2)),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(pref, style: AppTextStyles.caption.copyWith(color: AppColors.primary, fontWeight: FontWeight.w500)),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 16),
            child: Container(
              decoration: BoxDecoration(
                color: Colors.white,
                border: Border.all(color: AppColors.borderAlt),
                borderRadius: BorderRadius.circular(20),
              ),
              child: Column(
                children: [
                  _menuRow('Offline Maps & Saved Places'),
                  const Divider(height: 1, color: AppColors.border),
                  _menuRow('Language (English)'),
                  const Divider(height: 1, color: AppColors.border),
                  _menuRow('App Permissions'),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _statColumn(String value, String label) {
    return Expanded(
      child: Column(
        children: [
          Text(value, style: AppTextStyles.cardTitle.copyWith(fontSize: 19)),
          Text(label, style: AppTextStyles.caption, textAlign: TextAlign.center),
        ],
      ),
    );
  }

  Widget _menuRow(String label) {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Row(
        children: [
          Expanded(child: Text(label, style: AppTextStyles.bodyMedium.copyWith(fontWeight: FontWeight.w500))),
          const Icon(Icons.chevron_right, color: Color(0xFFC7C4BD)),
        ],
      ),
    );
  }
}
