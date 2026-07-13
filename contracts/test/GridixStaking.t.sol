// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {GridixStaking} from "../src/GridixStaking.sol";
import {MockUSDC} from "./mocks/MockUSDC.sol";
import {ReentrantToken, IReentrancyHook} from "./mocks/ReentrantToken.sol";
import {IAccessControl} from "@openzeppelin/contracts/access/IAccessControl.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// Re-enters withdraw() or settleBatch() from inside the token transfer callback of withdraw().
contract StakingReentrancyAttacker is IReentrancyHook {
    GridixStaking public staking;
    ReentrantToken public token;
    uint8 public mode; // 1 = re-enter withdraw, 2 = re-enter settleBatch

    constructor(GridixStaking staking_, ReentrantToken token_) {
        staking = staking_;
        token = token_;
    }

    function trigger(uint8 mode_) external {
        mode = mode_;
        token.arm(address(this)); // token calls hook() when it transfers earnings to us
        staking.withdraw();
    }

    function hook() external override {
        if (mode == 1) {
            staking.withdraw();
        } else {
            address[] memory p = new address[](1);
            uint256[] memory a = new uint256[](1);
            p[0] = address(this);
            a[0] = 1;
            staking.settleBatch(p, a);
        }
    }
}

contract GridixStakingTest is Test {
    GridixStaking internal staking;
    MockUSDC internal usdc;

    address internal admin = makeAddr("admin");
    address internal coordinator = makeAddr("coordinator");
    address internal arbiter = makeAddr("arbiter");
    address internal treasury = makeAddr("treasury");
    address internal prov = makeAddr("prov");
    address internal outsider = makeAddr("outsider");

    uint256 internal constant USDC = 1e6;
    uint256 internal constant MIN_STAKE = 100 * USDC;
    uint256 internal constant COOLDOWN = 7 days; // > Session 10 detection + dispute window

    bytes32 internal coordRole;
    bytes32 internal arbiterRole;
    bytes32 internal adminRole;

    function setUp() public {
        usdc = new MockUSDC();
        staking = new GridixStaking(address(usdc), admin, coordinator, arbiter, treasury, MIN_STAKE, COOLDOWN);
        coordRole = staking.COORDINATOR_ROLE();
        arbiterRole = staking.ARBITER_ROLE();
        adminRole = staking.DEFAULT_ADMIN_ROLE();
        usdc.mint(prov, 10_000 * USDC);
        vm.prank(prov);
        usdc.approve(address(staking), type(uint256).max);
    }

    function _stake(address who, uint256 amount) internal {
        vm.prank(who);
        staking.stake(amount);
    }

    function _fundPool(uint256 amount) internal {
        usdc.mint(coordinator, amount);
        vm.startPrank(coordinator);
        usdc.approve(address(staking), amount);
        staking.depositSettlement(amount);
        vm.stopPrank();
    }

    // ── happy path ───────────────────────────────────────────────────────────────

    function test_HappyPath_Stake_Settle_Withdraw_Unstake() public {
        _stake(prov, 200 * USDC);
        assertEq(staking.stakeOf(prov), 200 * USDC);
        assertTrue(staking.hasMinimumStake(prov));

        _fundPool(50 * USDC);
        address[] memory p = new address[](1);
        uint256[] memory a = new uint256[](1);
        p[0] = prov;
        a[0] = 40 * USDC;
        vm.prank(coordinator);
        staking.settleBatch(p, a);
        assertEq(staking.earningsOf(prov), 40 * USDC);
        assertEq(staking.settlementPool(), 10 * USDC);

        uint256 before = usdc.balanceOf(prov);
        vm.prank(prov);
        staking.withdraw();
        assertEq(usdc.balanceOf(prov), before + 40 * USDC);
        assertEq(staking.earningsOf(prov), 0);

        // Unstake with cooldown.
        vm.prank(prov);
        staking.unstake(200 * USDC);
        (uint256 amt, uint256 unlockAt) = staking.unstakingOf(prov);
        assertEq(amt, 200 * USDC);
        assertEq(unlockAt, block.timestamp + COOLDOWN);
        assertEq(staking.stakeOf(prov), 0);
        assertFalse(staking.hasMinimumStake(prov));

        vm.warp(block.timestamp + COOLDOWN);
        uint256 b2 = usdc.balanceOf(prov);
        vm.prank(prov);
        staking.completeUnstake();
        assertEq(usdc.balanceOf(prov), b2 + 200 * USDC);
    }

    // ── batch settlement gas: N in 1 tx vs N separate txs ────────────────────────

    function test_Gas_SettleBatch_vs_Individual() public {
        uint256 n = 50;
        _fundPool(1000 * USDC);
        // Two DISJOINT, fresh provider sets so both paths pay the same cold-storage cost — an
        // apples-to-apples comparison (reusing addresses would let the second path hit warm
        // slots and understate the batch win).
        address[] memory batchP = new address[](n);
        uint256[] memory batchA = new uint256[](n);
        for (uint256 i = 0; i < n; i++) {
            batchP[i] = address(uint160(uint256(keccak256(abi.encode("batch", i)))));
            batchA[i] = 1 * USDC;
        }

        vm.prank(coordinator);
        uint256 g0 = gasleft();
        staking.settleBatch(batchP, batchA);
        uint256 batchGas = g0 - gasleft();

        // N separate settleBatch([one]) calls, each to a fresh provider.
        uint256 indivExec;
        for (uint256 i = 0; i < n; i++) {
            address[] memory p1 = new address[](1);
            uint256[] memory a1 = new uint256[](1);
            p1[0] = address(uint160(uint256(keccak256(abi.encode("indiv", i)))));
            a1[0] = 1 * USDC;
            vm.prank(coordinator);
            uint256 g1 = gasleft();
            staking.settleBatch(p1, a1);
            indivExec += g1 - gasleft();
        }
        // Each separate call is also a separate transaction: add the 21000 intrinsic per tx.
        uint256 individualTotal = indivExec + n * 21000;

        console.log("settleBatch(50) gas:      ", batchGas);
        console.log("50x separate (+intrinsic):", individualTotal);
        console.log("saved gas:                ", individualTotal - batchGas);
        console.log("saved permille of indiv:  ", (individualTotal - batchGas) * 1000 / individualTotal);

        assertLt(batchGas, individualTotal);
    }

    function test_Revert_SettleBatch_LengthMismatch() public {
        _fundPool(10 * USDC);
        address[] memory p = new address[](2);
        uint256[] memory a = new uint256[](1);
        p[0] = prov;
        p[1] = outsider;
        a[0] = 1 * USDC;
        vm.prank(coordinator);
        vm.expectRevert(GridixStaking.LengthMismatch.selector);
        staking.settleBatch(p, a);
    }

    function test_Revert_SettleBatch_ExceedsFunds() public {
        _fundPool(5 * USDC);
        address[] memory p = new address[](1);
        uint256[] memory a = new uint256[](1);
        p[0] = prov;
        a[0] = 6 * USDC;
        vm.prank(coordinator);
        vm.expectRevert(abi.encodeWithSelector(GridixStaking.InsufficientSettlementFunds.selector, 6 * USDC, 5 * USDC));
        staking.settleBatch(p, a);
    }

    function test_Revert_SettleBatch_ByNonCoordinator() public {
        _fundPool(10 * USDC);
        address[] memory p = new address[](1);
        uint256[] memory a = new uint256[](1);
        p[0] = prov;
        a[0] = 1 * USDC;
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, coordRole)
        );
        vm.prank(outsider);
        staking.settleBatch(p, a);
    }

    // ── slashing + dispute hold ──────────────────────────────────────────────────

    function test_Slash_Dispute_Overturned_StakeIntact() public {
        _stake(prov, 500 * USDC);
        bytes32 ev = keccak256("session10-evidence");

        vm.prank(coordinator);
        staking.slash(prov, 300 * USDC, ev);
        // Held: removed from active stake, parked in dispute, NOT burned yet.
        assertEq(staking.stakeOf(prov), 200 * USDC);
        (uint256 dAmt, bytes32 dEv, bool open) = staking.disputeOf(prov);
        assertEq(dAmt, 300 * USDC);
        assertEq(dEv, ev);
        assertTrue(open);
        assertEq(usdc.balanceOf(treasury), 0); // nothing moved out

        // Overturned → full stake returns, nothing lost.
        vm.prank(arbiter);
        staking.resolveDispute(prov, false);
        assertEq(staking.stakeOf(prov), 500 * USDC);
        assertEq(usdc.balanceOf(treasury), 0);
        (,, open) = staking.disputeOf(prov);
        assertFalse(open);
        assertEq(usdc.balanceOf(address(staking)), 500 * USDC);
    }

    function test_Slash_Dispute_Upheld_ToTreasury() public {
        _stake(prov, 500 * USDC);
        vm.prank(coordinator);
        staking.slash(prov, 300 * USDC, keccak256("ev"));
        vm.prank(arbiter);
        staking.resolveDispute(prov, true);
        assertEq(usdc.balanceOf(treasury), 300 * USDC); // executed
        assertEq(staking.stakeOf(prov), 200 * USDC);
        assertEq(usdc.balanceOf(address(staking)), 200 * USDC);
    }

    function test_Slash_TakesFromCoolingBucket() public {
        _stake(prov, 500 * USDC);
        vm.prank(prov);
        staking.unstake(400 * USDC); // active=100, cooling=400
        vm.prank(coordinator);
        staking.slash(prov, 300 * USDC, keccak256("ev")); // 100 from active, 200 from cooling
        assertEq(staking.stakeOf(prov), 0);
        (uint256 coolAmt,) = staking.unstakingOf(prov);
        assertEq(coolAmt, 200 * USDC);
        (uint256 dAmt,,) = staking.disputeOf(prov);
        assertEq(dAmt, 300 * USDC);
    }

    function test_Revert_Slash_ByNonCoordinator() public {
        _stake(prov, 100 * USDC);
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, coordRole)
        );
        vm.prank(outsider);
        staking.slash(prov, 1 * USDC, keccak256("ev"));
    }

    function test_Revert_Slash_ExceedsStake() public {
        _stake(prov, 100 * USDC);
        vm.prank(coordinator);
        vm.expectRevert(abi.encodeWithSelector(GridixStaking.InsufficientStake.selector, 101 * USDC, 100 * USDC));
        staking.slash(prov, 101 * USDC, keccak256("ev"));
    }

    function test_Revert_Slash_DisputeAlreadyOpen() public {
        _stake(prov, 100 * USDC);
        vm.startPrank(coordinator);
        staking.slash(prov, 10 * USDC, keccak256("ev"));
        vm.expectRevert(GridixStaking.DisputeAlreadyOpen.selector);
        staking.slash(prov, 10 * USDC, keccak256("ev2"));
        vm.stopPrank();
    }

    function test_Revert_ResolveDispute_ByNonArbiter() public {
        _stake(prov, 100 * USDC);
        vm.prank(coordinator);
        staking.slash(prov, 10 * USDC, keccak256("ev"));
        // Even the coordinator (who slashed) cannot resolve — arbiter is a separate role.
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, coordinator, arbiterRole)
        );
        vm.prank(coordinator);
        staking.resolveDispute(prov, true);
    }

    function test_Revert_ResolveDispute_NoOpenDispute() public {
        vm.prank(arbiter);
        vm.expectRevert(GridixStaking.NoOpenDispute.selector);
        staking.resolveDispute(prov, true);
    }

    // ── cooldown ─────────────────────────────────────────────────────────────────

    function test_Revert_CompleteUnstake_BeforeCooldown() public {
        _stake(prov, 200 * USDC);
        vm.prank(prov);
        staking.unstake(200 * USDC);
        (, uint256 unlockAt) = staking.unstakingOf(prov);
        vm.prank(prov);
        vm.expectRevert(abi.encodeWithSelector(GridixStaking.CooldownActive.selector, unlockAt));
        staking.completeUnstake();
    }

    function test_Revert_CompleteUnstake_NothingUnstaking() public {
        vm.prank(prov);
        vm.expectRevert(GridixStaking.NothingUnstaking.selector);
        staking.completeUnstake();
    }

    function test_Revert_Unstake_ExceedsStake() public {
        _stake(prov, 100 * USDC);
        vm.prank(prov);
        vm.expectRevert(abi.encodeWithSelector(GridixStaking.InsufficientStake.selector, 101 * USDC, 100 * USDC));
        staking.unstake(101 * USDC);
    }

    // ── reentrancy ───────────────────────────────────────────────────────────────

    function _reentrancySetup() internal returns (GridixStaking evilStaking, StakingReentrancyAttacker attacker) {
        ReentrantToken evil = new ReentrantToken();
        evilStaking = new GridixStaking(address(evil), admin, coordinator, arbiter, treasury, MIN_STAKE, COOLDOWN);
        attacker = new StakingReentrancyAttacker(evilStaking, evil);
        // Fund the pool and settle earnings to the attacker so withdraw() will pay it.
        evil.mint(coordinator, 100 * USDC);
        vm.startPrank(coordinator);
        evil.approve(address(evilStaking), 100 * USDC);
        evilStaking.depositSettlement(100 * USDC);
        address[] memory p = new address[](1);
        uint256[] memory a = new uint256[](1);
        p[0] = address(attacker);
        a[0] = 10 * USDC;
        evilStaking.settleBatch(p, a);
        vm.stopPrank();
    }

    function test_Revert_Reentrancy_Withdraw() public {
        (, StakingReentrancyAttacker attacker) = _reentrancySetup();
        vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
        attacker.trigger(1); // withdraw -> token callback -> re-enter withdraw
    }

    function test_Revert_Reentrancy_SettleBatch() public {
        (GridixStaking evilStaking, StakingReentrancyAttacker attacker) = _reentrancySetup();
        // Give the attacker the coordinator role so the reentrant settleBatch clears the role
        // check — proving the ReentrancyGuard (which runs first) is what stops it.
        vm.prank(admin);
        evilStaking.grantRole(coordRole, address(attacker));
        vm.expectRevert(ReentrancyGuard.ReentrancyGuardReentrantCall.selector);
        attacker.trigger(2); // withdraw -> token callback -> re-enter settleBatch
    }

    // ── pausable ─────────────────────────────────────────────────────────────────

    function test_Revert_WhenPaused() public {
        _stake(prov, 100 * USDC);
        vm.prank(admin);
        staking.pause();
        vm.prank(prov);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        staking.stake(1 * USDC);
        vm.prank(prov);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        staking.unstake(1 * USDC);
        vm.prank(prov);
        vm.expectRevert(Pausable.EnforcedPause.selector);
        staking.withdraw();
    }

    function test_Unpause_Resumes() public {
        vm.startPrank(admin);
        staking.pause();
        staking.unpause();
        vm.stopPrank();
        _stake(prov, 100 * USDC);
        assertEq(staking.stakeOf(prov), 100 * USDC);
    }

    // ── admin ────────────────────────────────────────────────────────────────────

    function test_Admin_Setters() public {
        vm.startPrank(admin);
        staking.setMinStake(50 * USDC);
        staking.setCooldownPeriod(3 days);
        address t2 = makeAddr("t2");
        staking.setTreasury(t2);
        vm.stopPrank();
        assertEq(staking.minStake(), 50 * USDC);
        assertEq(staking.cooldownPeriod(), 3 days);
        assertEq(staking.treasury(), t2);
    }

    function test_Revert_SetMinStake_ByNonAdmin() public {
        vm.expectRevert(
            abi.encodeWithSelector(IAccessControl.AccessControlUnauthorizedAccount.selector, outsider, adminRole)
        );
        vm.prank(outsider);
        staking.setMinStake(1);
    }

    function test_Revert_Constructor_ZeroAddress() public {
        vm.expectRevert(GridixStaking.ZeroAddress.selector);
        new GridixStaking(address(0), admin, coordinator, arbiter, treasury, MIN_STAKE, COOLDOWN);
    }

    function test_Revert_SetTreasury_ZeroAddress() public {
        vm.prank(admin);
        vm.expectRevert(GridixStaking.ZeroAddress.selector);
        staking.setTreasury(address(0));
    }

    function test_Revert_ZeroAmounts() public {
        vm.prank(prov);
        vm.expectRevert(GridixStaking.ZeroAmount.selector);
        staking.stake(0);
        vm.prank(prov);
        vm.expectRevert(GridixStaking.ZeroAmount.selector);
        staking.unstake(0);
        vm.prank(coordinator);
        vm.expectRevert(GridixStaking.ZeroAmount.selector);
        staking.slash(prov, 0, keccak256("ev"));
        vm.prank(coordinator);
        vm.expectRevert(GridixStaking.ZeroAmount.selector);
        staking.depositSettlement(0);
    }

    function test_Revert_Withdraw_NothingToWithdraw() public {
        vm.prank(prov);
        vm.expectRevert(GridixStaking.NothingToWithdraw.selector);
        staking.withdraw();
    }

    function test_RoleSeparation() public view {
        assertTrue(staking.hasRole(adminRole, admin));
        assertTrue(staking.hasRole(coordRole, coordinator));
        assertTrue(staking.hasRole(arbiterRole, arbiter));
        assertFalse(staking.hasRole(coordRole, admin));
        assertFalse(staking.hasRole(arbiterRole, coordinator));
        assertFalse(staking.hasRole(adminRole, coordinator));
    }

    // ── fuzz: stake accounting invariant ─────────────────────────────────────────

    function testFuzz_StakeAccounting(uint96 stakeAmt, uint96 unstakeAmt, uint96 slashAmt) public {
        uint256 s = bound(uint256(stakeAmt), 1, 1e15);
        usdc.mint(prov, s);
        vm.prank(prov);
        staking.stake(s);

        uint256 us = bound(uint256(unstakeAmt), 0, s);
        if (us > 0) {
            vm.prank(prov);
            staking.unstake(us);
        }
        uint256 expActive = s - us;
        uint256 expCooling = us;

        uint256 sl = bound(uint256(slashAmt), 0, s); // slashable == active + cooling == s
        uint256 expDispute;
        if (sl > 0) {
            vm.prank(coordinator);
            staking.slash(prov, sl, keccak256("ev"));
            expDispute = sl;
            if (sl <= expActive) {
                expActive -= sl;
            } else {
                uint256 rem = sl - expActive;
                expActive = 0;
                expCooling -= rem;
            }
        }

        assertEq(staking.stakeOf(prov), expActive);
        (uint256 coolAmt,) = staking.unstakingOf(prov);
        assertEq(coolAmt, expCooling);
        (uint256 dAmt,,) = staking.disputeOf(prov);
        assertEq(dAmt, expDispute);
        // Nothing left the contract yet — every unit is still accounted for.
        assertEq(usdc.balanceOf(address(staking)), expActive + expCooling + expDispute);
        assertEq(expActive + expCooling + expDispute, s);
    }
}
