import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../models/companion.dart';
import '../../providers/companion_provider.dart';
import '../../theme/theme.dart';
import '../../widgets/figma_chrome.dart';
import '../../widgets/primary_button.dart';
import '../../widgets/progress_dots.dart';

class ChooseBuddyScreen extends StatefulWidget {
  const ChooseBuddyScreen({
    super.key,
    required this.onContinue,
    required this.onBack,
    this.showProgress = true,
  });

  final VoidCallback onContinue;
  final VoidCallback onBack;
  final bool showProgress;

  @override
  State<ChooseBuddyScreen> createState() => _ChooseBuddyScreenState();
}

class _ChooseBuddyScreenState extends State<ChooseBuddyScreen> {
  late CompanionId _selected;

  @override
  void initState() {
    super.initState();
    _selected = context.read<CompanionProvider>().selected.id;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.backgroundAlt,
      body: FigmaDeviceFrameWrapper(
        backgroundColor: AppColors.backgroundAlt,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  IconButton(
                    onPressed: widget.onBack,
                    icon: const Icon(Icons.chevron_left, size: 28),
                  ),
                  if (widget.showProgress) const ProgressDots(step: 2),
                ],
              ),
            ),
            const SizedBox(height: 40),
            Column(
              children: [
                Text(
                  'Choose your travel buddy',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.headingLarge,
                ),
                const SizedBox(height: 12),
                Text(
                  'Your companion will guide you through Seoul.',
                  style: AppTextStyles.bodyMedium.copyWith(color: AppColors.textSecondary),
                ),
              ],
            ),
            const SizedBox(height: 24),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              alignment: WrapAlignment.center,
              children: [
                for (final companion in kCompanionGridOrder)
                  _BuddyCard(
                    companion: companion,
                    selected: companion.id == _selected,
                    onTap: () => setState(() => _selected = companion.id),
                  ),
              ],
            ),
            const Spacer(),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
              child: PrimaryButton(
                label: 'Select & Continue',
                onPressed: () {
                  context.read<CompanionProvider>().selectCompanion(_selected);
                  widget.onContinue();
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BuddyCard extends StatelessWidget {
  const _BuddyCard({required this.companion, required this.selected, required this.onTap});

  final Companion companion;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 100,
        height: 108,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(
            color: selected ? const Color(0xFF5E836A) : AppColors.borderAlt,
            width: selected ? 2 : 1,
          ),
        ),
        child: Stack(
          children: [
            Center(
              child: Image.asset(companion.portraitAsset, fit: BoxFit.contain),
            ),
            if (selected)
              Positioned(
                top: -4,
                right: -4,
                child: Container(
                  width: 22,
                  height: 22,
                  decoration: BoxDecoration(
                    color: AppColors.chipBackground,
                    shape: BoxShape.circle,
                    border: Border.all(color: AppColors.primary, width: 1.5),
                  ),
                  child: const Icon(Icons.check, size: 14, color: AppColors.primary),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
