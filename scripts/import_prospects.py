"""Run from repository root: python -m scripts.import_prospects prospects.csv"""
import argparse
import asyncio
import csv
from sqlalchemy.exc import IntegrityError
from app.database import init_db, Session, engine
from app.models import Prospect
from app.schemas import ProspectCreate


async def run(path):
    await init_db()
    count = 0
    with open(path, newline='', encoding='utf-8-sig') as file:
        async with Session() as db:
            for line, row in enumerate(csv.DictReader(file), 2):
                if not row.get('mobile_phone'):
                    row['mobile_phone'] = None
                try:
                    body = ProspectCreate.model_validate(row)
                    db.add(Prospect(**body.model_dump()))
                    await db.commit()
                    count += 1
                except (ValueError, IntegrityError) as exc:
                    await db.rollback()
                    print(f'Riga {line}: non importata ({type(exc).__name__}); controlla formato e duplicati.')
    await engine.dispose()
    print(f'Importati {count} prospect.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    asyncio.run(run(parser.parse_args().csv))
