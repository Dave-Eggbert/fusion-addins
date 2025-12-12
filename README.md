# Addins for Autodesk Fusion 360

This code is in alpha state and there are no guarantees that this will work correctly for your use case.
Furthermore, updates to this code might break existing usages of the addins.

## Addins

- **Lamello**

  This currently places access and guide holes for Lamello Clamex P10 and P14 connectors.
- **Pattern Cutouts**

  This is a collection of differently shaped pattern cutouts, e.g. triangles, rhombuses etc.

  The Froli pattern computes the best froli grid for a given rectangular surface and places cutouts accordingly.

  The adaptive cutout takes out all the material, but takes features within the face into account and leaves material around them.
  If the cutout goes all the way through the board, it will attach the material for inner features to the outer rim of the board.
- **Concealed Hinge**

  This places holes for concealed hinges in the door and carcass boards. Currently there's just one type of hinge implemented (Blum cliptop 110 for thin doors).
- **Door Latch**

  Places holes for door latches in the door and carcass boards. Currently this supports Everlocks and the small 44mm pull locks.

## Installation

Just place the addins you want to use in your Fusion Addin directory. On the mac this is `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns`.

Then go Fusion's Addin panel:

![](img/doc1.png)

In there you can run the addin by switching on the run toggle. Optionally, you can enable the run-on-startup checkbox, so that you don't have to repeat this process each time you launch Fusion.

![](img/doc2.png)

## Development

To work on the addins, make sure you have VS Code installed, right-click on the plugin's name in Fusion's addin panel and choose "Edit in code editor".

![](img/doc3.png)

## License

GNU General Public License v3.0 or later

See [COPYING](COPYING) to see the full text.

## Attributions

- Lock icon by karl from [Noun Project](https://thenounproject.com/browse/icons/term/lock/) (CC BY 3.0)
- Hinage icon by Ruslan Dezign from [Noun Project](https://thenounproject.com/browse/icons/term/lock/) (CC BY 3.0)
- Triangular pattern icon by Made x Made from [Noun Project](https://thenounproject.com/browse/icons/term/lock/) (CC BY 3.0)