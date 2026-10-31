"""Regular rewards and explicitly authorized gold quick replenishments."""
import re


def attempts(text):
    match = re.search(r'попыток за день\s*:\s*(\d{1,2})\b', text)
    return int(match[1]) if match else None


def collect(bot):
    from bot import Paused
    bot.enter_campaign()
    bot.tap(580, 865)
    bot.require('текущие награды')
    if bot.has('получить', (750, 720, 1170, 845)):
        bot.click('получить', (750, 720, 1170, 845))
        if bot.rewards_open():
            bot.confirm_rewards()
        bot.log('Пополнение кампании: обычные награды собраны')
    else:
        bot.back()
    bot.require('скорость пополнения')
    for _ in range(20):
        bot.tap(1325, 865)
        bot.require('быстрое пополнение', 'попыток за день')
        remaining = attempts(bot.text())
        if remaining is None:
            raise Paused('Быстрое пополнение: не прочитан дневной остаток')
        if remaining == 0:
            bot.log('Быстрое пополнение: дневной лимит исчерпан')
            bot.tap(1410, 200)
            break
        region = (750, 690, 1170, 820)
        if bot.has('бесплатно', region):
            bot.click('бесплатно', region)
        else:
            price = bot.detail((900, 750, 1100, 820)).strip()
            if not re.fullmatch(r'\d{1,5}', price) or int(price) <= 0:
                raise Paused('Быстрое пополнение: стоимость в золоте не распознана')
            bot.require('забрать')
            bot.log(f'Быстрое пополнение: {price} золота; доступно {remaining} попыток')
            bot.click('забрать', region)
        bot.wait(1)
        bot.observe()
        bot.confirm_rewards()
        bot.require('скорость пополнения')
        bot.tap(1325, 865)
        bot.require('быстрое пополнение')
        after = attempts(bot.text())
        if after is None or after != remaining - 1:
            raise Paused('Быстрое пополнение: уменьшение остатка не подтверждено; повтор отменён')
        bot.tap(1410, 200)
    else:
        raise Paused('Быстрое пополнение: превышено число проверок')
    bot.tap(100, 50)
    bot.main()
