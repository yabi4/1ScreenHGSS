// Build the evolution play-test save from a complete HGSS save. See docs/DEVELOPMENT.md.
//   dotnet run --project tools/testsaves -- <complete.sav> <pkhex-out.sav>
using System;
using System.IO;
using System.Linq;
using PKHeX.Core;

var sav = (SAV4HGSS)SaveUtil.GetSaveFile(args[0])!;
var strings = GameInfo.GetStrings("fr");
var rng = new Random(20261019);

// level before evolving -> the move the evolved form learns at the next level
var bugs = new (ushort Species, byte Level)[] { (10, 6), (13, 6), (265, 6), (401, 9) };
ushort[] moves = { 33, 81, 450, 182 };      // Tackle, String Shot, Bug Bite, Protect

int box = 0, slot = 0;
(int, int) NextEmpty()
{
    for (; box < sav.BoxCount; box++, slot = 0)
        for (; slot < sav.BoxSlotCount; slot++)
            if (sav.GetBoxSlotAtIndex(box, slot).Species == 0)
                return (box, slot++);
    throw new Exception("no room in the PC");
}

for (int i = 0; i < bugs.Length; i++)
{
    int party = 2 + i;
    var old = sav.GetPartySlotAtIndex(party);
    var (b, s) = NextEmpty();
    sav.SetBoxSlotAtIndex(old, b, s);
    Console.WriteLine($"moved {strings.specieslist[old.Species]} to box {b + 1} slot {s + 1}");

    var pk = (PK4)old.Clone();
    var (species, level) = bugs[i];
    pk.Species = species;
    pk.Form = 0;
    pk.PID = (uint)rng.NextInt64(0, 1L << 32);
    pk.Gender = EntityGender.GetFromPID(species, pk.PID);
    pk.RefreshAbility(0);
    pk.IsEgg = false;
    pk.IsNicknamed = false;
    pk.Nickname = SpeciesName.GetSpeciesNameGeneration(species, pk.Language, 4);
    pk.HeldItem = 0;
    pk.EXP = Experience.GetEXP((byte)(level + 1), pk.PersonalInfo.EXPGrowth) - 1;
    pk.SetMoves(moves);
    pk.SetMaximumPPCurrent(moves);
    pk.ResetPartyStats();
    pk.Heal();
    pk.RefreshChecksum();
    sav.SetPartySlotAtIndex(pk, party);
    Console.WriteLine($"party {party + 1}: {pk.Nickname} lv{pk.CurrentLevel} exp {pk.EXP}, next level at {Experience.GetEXP((byte)(level + 1), pk.PersonalInfo.EXPGrowth)}");
}
File.WriteAllBytes(args[1], sav.Write().ToArray());
var check = (SAV4HGSS)SaveUtil.GetSaveFile(args[1])!;
Console.WriteLine($"written; PKHeX reads it back with checksums {(check.ChecksumsValid ? "valid" : "INVALID")}, party " +
    string.Join(", ", check.PartyData.Select(p => $"{strings.specieslist[p.Species]} {p.CurrentLevel}")));
